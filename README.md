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
- [ ] Actually run training and evaluate against the original
      `yolo11_anpr_ghd.pt` weights
- [ ] Retrain the character OCR step (digit extraction / classifier) on
      IR-LPR's per-character boxes — not started
