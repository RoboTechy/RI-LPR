# Trained models

`ir_lpr_plate_detector.pt` — YOLO11n fine-tuned on the full IR-LPR
"Car Image" dataset (14671 train / 2120 val images), via
`scripts/train_plate_detector.py`. Validation results (50 epochs):

| metric | value |
|---|---|
| Precision | 0.964 |
| Recall | 0.945 |
| mAP50 | 0.981 |
| mAP50-95 | 0.775 |

This replaces the original `yolo11_anpr_ghd.pt` (repo root), which was
only fine-tuned on ~400 images. `license_plate_extractor.py` uses this
model by default and falls back to `yolo11_anpr_ghd.pt` if it's missing.

After running `scripts/train_plate_detector.py` locally, copy your best
checkpoint here:

```bash
cp runs/detect/ir_lpr_plate_detector/weights/best.pt models/ir_lpr_plate_detector.pt
```
