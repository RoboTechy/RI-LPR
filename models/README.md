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

`CharCNN` reached **94.2%** per-character val accuracy - better, but
0.942^8 ≈ 61% full-plate accuracy is still not great, and an
end-to-end test on a real photo showed the classifier wasn't even the
main problem: `extract_digits()`'s classical segmentation
(threshold + connected components) only found 7 of 8 characters on
that photo. See `ir_lpr_char_detector.pt` below, which replaces
classification *and* segmentation together.

`ir_lpr_char_detector.pt` — multi-class YOLO11n that detects and reads
every character on an already-cropped plate in one pass (class names
are the characters themselves), via
`scripts/convert_char_detection_dataset.py` +
`scripts/train_char_detector.py` (100 epochs). After running that
script locally, copy the checkpoint here:

```bash
cp runs/detect/ir_lpr_char_detector/weights/best.pt models/ir_lpr_char_detector.pt
```

**Result: found all 8/8 characters, correctly, on all 4 of the repo's
sample photos (`car_a.jpg`-`car_d.jpg`)** via `scripts/recognize_plate_v2.py`
- a clean sweep, and every plate's letter landed in the correct
position (index 2) with no digit/letter type mismatches, entirely on
its own (no manual layout correction needed). This is the pipeline to
use going forward; `ir_lpr_char_classifier.pt` (classification only,
paired with classical segmentation) is kept for reference but
segmentation was its real bottleneck, not classification accuracy.
