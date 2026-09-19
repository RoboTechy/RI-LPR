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

`ir_lpr_char_classifier.pt` + `ir_lpr_char_classifier_classes.json` —
character classifier retrained on IR-LPR's per-character boxes, via
`scripts/convert_char_annotations.py` + `scripts/train_char_classifier.py`
(both scripts write these files directly to this folder - no manual
copy needed). See the main README's "Retraining the character OCR
step" section.

First attempt used `FCModel` (a flat 3-layer MLP, matching the
upstream repo's original architecture) and plateaued at **91.5%**
per-character validation accuracy after 30 epochs. Not good enough:
errors compound across all ~8 characters on a plate, so
0.915^8 ≈ 49% chance of reading an entire plate correctly. Switched to
`CharCNN` (a small 2-conv-layer CNN, ~210K params - still cheap enough
for real-time CPU inference) plus light rotation/translation
augmentation on the train split, since flattening the image (what
FCModel does) throws away spatial structure a CNN can use. `FCModel` is
kept in `image_classifier.py` for backward compatibility with the
original `persian_digit_classifier.pt`, but new training uses `CharCNN`.
