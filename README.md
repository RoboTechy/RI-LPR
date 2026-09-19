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

## Next up

- [ ] Re-test the truck path on a higher-resolution photo - the one
      available for testing was 416x416 (a Roboflow export), too low-res
      for the character detector to read reliably; the fallback
      *detection* worked, but end-to-end truck accuracy is still unverified
- [ ] Production prep for the CPU-only 20-core server: export both YOLO
      models (plate detector + character detector) to ONNX for faster
      CPU inference (`model.export(format="onnx")`)
- [ ] Resolve the licensing question (see "Licensing note" above)
      before any public release
