# RI-LPR — Iranian License Plate Recognition

Personal project to build an Iranian (Persian) license plate detection and
recognition pipeline, running on CPU/consumer GPU.

## Plan

1. **Base codebase**: forked from
   [Gholamrezadar/yolo11-persian-license-plate-recognition](https://github.com/Gholamrezadar/yolo11-persian-license-plate-recognition)
   — YOLO11 for plate detection + OpenCV digit extraction + a Persian
   character classifier. Kept as-is for now (see `ORIGINAL_README.md` for
   the upstream author's own documentation).
2. **Training data**: the original codebase was fine-tuned on only ~400
   images. We plan to retrain the detection/classification models on the
   much larger [IR-LPR dataset](dataset/IR-LPR/README.md) (~21k car images,
   ~28k plate images) from Malek Ashtar University of Technology, to
   improve accuracy and generalization.
3. Training will run locally (13th-gen i7, RTX 4050 6GB VRAM, 32GB RAM) —
   sufficient for fine-tuning YOLO11n/s at moderate batch sizes.

## Repository layout

- `*.ipynb`, `*.py` — original YOLO11 detection + digit extraction +
  character classifier code (from Gholamrezadar's repo).
- `*.pt` — pretrained weights shipped with the upstream repo
  (`yolo11n.pt` base weights, `yolo11_anpr_ghd.pt` fine-tuned on the
  original small dataset, `persian_digit_classifier.pt` character
  classifier).
- `results/` — sample outputs from the upstream repo.
- `dataset/IR-LPR/` — reference material (README + license) for the
  IR-LPR dataset. **The actual images are not in this repo** — they're
  multi-gigabyte files hosted on Google Drive; see
  `dataset/IR-LPR/README.md` for download links.

## Getting the training data (run locally, not in a cloud sandbox)

The IR-LPR "Car Image" set (full car photos + plate bounding boxes) is
what we need to retrain plate detection. It's large (train ~8.3GB, val
~1.2GB, test ~2.3GB) and hosted on Google Drive, and training needs your
GPU — so this step runs on your own machine, not in a remote session.

```bash
pip install -r requirements.txt
python scripts/download_ir_lpr.py          # downloads + extracts train and val
```

Then convert the annotations (Pascal-VOC-style XML, one whole-plate box
per image labeled "کل ناحیه پلاک") to YOLO label format:

```bash
python scripts/convert_annotations_to_yolo.py
```

This links images into `data/IR-LPR/car-image/{train,val}/images/`,
writes matching YOLO `.txt` labels under `.../labels/`, and writes
`data/IR-LPR/car-image/data.yaml` for Ultralytics. (Images are matched
to annotations by the *xml file's own name*, not the `<filename>` tag
inside it, which is stale — see the script's docstring.)

## Training

```bash
python scripts/train_plate_detector.py
```

Fine-tunes YOLO11n on the converted dataset. Defaults are picked for a
6GB-VRAM laptop GPU (auto batch-size selection, mixed precision).
Results land in `runs/detect/ir_lpr_plate_detector/` (gitignored —
`weights/best.pt` is the model to use afterward). See
`--help` for options (epochs, image size, a bigger `yolo11s.pt` base, etc).

## Retraining the character OCR step

The digit/character classifier (`image_classifier.py`'s `FCModel`) was
only trained on the upstream repo's small dataset. IR-LPR's XML
annotations also include a box per individual plate character (digit
or Persian letter), so we can retrain it too:

```bash
python scripts/convert_char_annotations.py   # crops characters into an ImageFolder layout
python scripts/train_char_classifier.py      # trains FCModel on them
```

`convert_char_annotations.py` preprocesses each crop (grayscale, CLAHE,
Otsu threshold) to match the domain `license_plate_extractor.py`
actually feeds the classifier at inference time — training on raw
photo crops instead would silently produce a model that looks fine in
validation but performs badly on real segmented digits, so this isn't
optional. Output goes to `data/IR-LPR/car-image/{train,val}/chars/<character>/`.

Training is fast (a tiny MLP on 28x28 images) even on CPU. It writes
`models/ir_lpr_char_classifier.pt` and
`models/ir_lpr_char_classifier_classes.json` (the class order, needed
at inference since it depends on whichever character folders exist on
the machine that trained it).

Try the full pipeline (detect → segment → classify) on a photo:

```bash
python scripts/recognize_plate.py car_a.jpg
```

Result: 94.2% per-character val accuracy (CharCNN, up from the flat
MLP's 91.5%), plus a plate-layout constraint in `recognize_plate.py`
(Iranian plates are 2 digits, 1 letter, 3 digits, 2 digits, so the
letter position can't be misread as a digit or vice versa when all 8
characters are found). But per-character accuracy alone caps
full-plate accuracy hard: 0.942**8 ≈ 61%. Tested end-to-end on a real
photo and the *segmentation* step - not classification - turned out to
be the bigger problem: it only found 7 of 8 characters, so the layout
constraint didn't even get to run. See the next section.

## Replacing segmentation with a character detector

The classical segmentation in `license_plate_extractor.py`
(CLAHE + Otsu threshold + connected components) regularly drops or
merges characters on real photos - it's the actual bottleneck, more
than classifier accuracy. IR-LPR's per-character boxes let us skip it
entirely: train a second, multi-class YOLO model that both locates
*and* identifies every character on the (already cropped) plate in one
pass.

```bash
python scripts/convert_char_detection_dataset.py   # crops the plate per annotation, writes YOLO multi-class labels
python scripts/train_char_detector.py              # trains yolo11n on it (100 epochs default - harder task, more classes)
python scripts/recognize_plate_v2.py car_a.jpg      # detect -> crop plate -> detect+read characters directly
```

`license_plate_extractor.py` was refactored to expose
`detect_and_crop_plate()` (car detection -> plate detection -> crop),
reused by both the old `extract_digits()` pipeline and this new one, so
neither duplicates that logic.

## Fine-tuning the plate detector for trucks

The real deployment target is a factory-gate camera reading truck plates
(front + one-side angled, plate close to the camera) — not the pure
side-profile shots most public truck datasets contain, and it's plate
*reading* accuracy that matters, not vehicle detection. `truck_plates/raw/`
holds a curated, manually-reviewed set of 253 real Iranian truck photos
with single-class `license-plate` boxes (drafted by
`scripts/prelabel_plate_boxes.py`, then hand-checked to drop false
positives and any pure side-view shots that don't match the real camera
angle).

We skipped Roboflow for this: the boxes were already drawn, so there was
nothing left for a labeling tool to do, and the free tier's constraints
(forced-public projects, a paid AI-assist feature we didn't need) weren't
worth the friction.

```bash
python scripts/prepare_truck_plate_dataset.py       # splits truck_plates/raw/ into data/truck-plates/{train,val}
python scripts/finetune_truck_plate_detector.py      # continues training models/ir_lpr_plate_detector.pt on it
```

This *continues* training the existing car-trained detector rather than
training a new one from base YOLO weights — see the script's docstring
for why the learning rate is lower and epoch count smaller than
`train_plate_detector.py`'s from-scratch run, and for the optional
`--freeze` flag and `--mix-car-images` dataset option, both aimed at the
same risk: a 253-image fine-tune overfitting or forgetting what the
model already knows about car plates. **Validate against the car val set
before replacing `models/ir_lpr_plate_detector.pt`** — the script prints
the exact command to do that at the end of training.

## Licensing note

- The upstream `yolo11-persian-license-plate-recognition` codebase does
  **not** include a LICENSE file (all rights reserved by default under
  GitHub's terms) — this needs to be resolved with the original author
  before any public redistribution of derived code.
- The IR-LPR dataset is released under **GPLv3** (see
  `dataset/IR-LPR/LICENSE`), which has copyleft implications for any
  derivative work that gets distributed.
- This repository is currently for personal/private use only.

## Status

- [x] Base codebase + dataset reference scaffolded
- [x] Dataset download script
- [x] Annotation conversion to YOLO format (verified: 14671/14671 train,
      2120/2120 val converted on a real download)
- [x] Training script
- [x] Plate detector retrained: precision=0.964, recall=0.945,
      mAP50=0.981, mAP50-95=0.775 (`models/ir_lpr_plate_detector.pt`)
- [x] End-to-end pipeline tested on a real photo (found and fixed an
      OpenCV 5.x compatibility bug in `straighten_skewed_rectangle`)
- [x] Character classifier retrained (CharCNN): 94.2% per-character val
      accuracy, up from FCModel's 91.5% — still not enough alone
      (0.942**8 ≈ 61% full-plate), plus a plate-layout constraint added
      to rule out digit/letter confusion by position
- [x] End-to-end test of that pipeline on a real photo: classifier
      wasn't the bottleneck, segmentation was (only found 7/8 characters)
- [x] Character-detector trained and tested: **8/8 characters read
      correctly on all 4 of the repo's sample photos**
      (`car_a.jpg`-`car_d.jpg`), letter always in the right position, no
      manual corrections needed (`models/ir_lpr_char_detector.pt`,
      `scripts/recognize_plate_v2.py`) — this is the recommended pipeline
      going forward, superseding the classify-then-segment approach

- [x] Tested on 6 more real photos from public Iranian vehicle datasets
      (not IR-LPR, not the repo's own samples): 4/5 cars read correctly
      end-to-end; found and fixed two real bugs along the way -
      `filter_boxes_by_class()` only recognized COCO class "car", so
      every truck photo was rejected before plate detection even ran;
      and once fixed, `ir_lpr_plate_detector.pt` (trained only on
      passenger cars) couldn't find a truck's plate either. Added a
      general-purpose (non-Iran-specific) plate-detection fallback
      (`open-image-models`) for vehicle types the fine-tuned detector
      never saw - confirmed working on a real truck photo, no new
      training data needed since a plate's rectangular shape doesn't
      depend on country or vehicle type

- [x] Tested end-to-end on 10 real Iranian truck photos (public dataset,
      416x416 Roboflow exports - low-res, a pessimistic proxy for a real
      factory-gate camera). Tried a larger fallback plate-detector variant
      (`yolo-v9-s-608` vs default `yolo-v9-t-384`) hoping for better
      small-object precision - made no real difference, sometimes
      slightly worse, so kept the faster default. Found 2/10 trucks were
      being misclassified as "bus" by the generic vehicle detector and
      dropped before plate detection ever ran; added bus(5) to
      `VEHICLE_CLASS_IDS` (harmless for this project - it only cares
      about reading plates, not vehicle type) - fixed one of those two
      outright (clean 8/8) and got the other from total failure to a
      partial read, plus fixed a car test image as a bonus (5/8 → 8/8).
      **Net: 4/10 trucks now read a structurally-plausible full plate**
      (up from 3/10), still well short of car-level (~90%+) reliability -
      remaining failures trace to genuinely low source-photo resolution
      and the lack of Iran-specific truck training data for either plate
      detector, not something fixable in code alone

- [x] Curated a real Iran-specific truck-plate dataset (253 images,
      cleaned of side-profile shots that don't match the actual
      factory-gate camera angle) and wrote
      `scripts/prepare_truck_plate_dataset.py` +
      `scripts/finetune_truck_plate_detector.py` to fine-tune
      `models/ir_lpr_plate_detector.pt` on it directly — skipped
      Roboflow, no labeling left to do once boxes are drafted

## Next up

- [ ] Run the truck fine-tune locally (GPU), validate against the car
      val set for regression, and re-test the 10-truck end-to-end suite
      (currently 4/10) to see the improvement
- [ ] Once real (better-quality) factory-gate camera photos are
      available, add them to `truck_plates/raw/` and re-run — the
      current 253-image set is still all from public sources, a
      pessimistic proxy for the real camera
- [ ] Production prep for the CPU-only 20-core server: export both YOLO
      models (plate detector + character detector) to ONNX for faster
      CPU inference (`model.export(format="onnx")`)
- [ ] Resolve the licensing question (see "Licensing note" above)
      before any public release
