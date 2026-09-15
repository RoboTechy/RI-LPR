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

🚧 Just scaffolded — next step is downloading the IR-LPR dataset and
adapting the training notebooks to it.
