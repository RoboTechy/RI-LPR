"""
One-off dataset export for later fine-tuning - NOT part of the
always-on worker process, and deliberately not added to docker-compose
as its own service (it's only needed for a few days while collecting
data, then it's gone). Run it on demand inside the already-running
worker container instead - it already has DB access and the media
volume mounted, so nothing extra needs to be built or started:

    docker compose exec worker python3 worker/export_training_dataset.py

For every DetectedPlate row whose confidence is at least
--min-confidence (default 0.75 - matches the extension's own "تشخیص
خوب" threshold) and that has a stored plate_box (only detections logged
AFTER this feature was added have one - see models.py/camera_worker.py),
writes into --out (default media/training_export/):

  <id>.jpg          the full vehicle image
  <id>.txt          the plate's bounding box, in YOLO format (one class,
                     "plate") - ready to use as-is for fine-tuning the
                     plate detector
  <id>_plate.jpg    the cropped plate image, named with its OCR'd text
                     for quick human review
  manifest.jsonl    one JSON line per exported detection: id, the full
                     OCR text (plate_text/short_format), each character
                     with its own confidence, overall confidence, which
                     camera/line, when, and whether an operator actually
                     used it (consumed) - the strongest correctness
                     signal available, see --only-consumed.

This does NOT include per-character bounding boxes (only the plate's
own box) - the character detector's per-box coordinates aren't
persisted anywhere yet, only the recognized text. Fine-tuning the plate
detector is fully covered; fine-tuning the character detector would
still need those images re-annotated (semi-)manually, or a follow-up
change to persist per-character boxes too.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

import cv2

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app import models  # noqa: E402
from app.config import MEDIA_ROOT  # noqa: E402
from app.database import SessionLocal  # noqa: E402


def to_yolo_line(box, img_width, img_height, class_id=0):
    x1, y1, x2, y2 = box
    x_center = (x1 + x2) / 2 / img_width
    y_center = (y1 + y2) / 2 / img_height
    width = (x2 - x1) / img_width
    height = (y2 - y1) / img_height
    return f"{class_id} {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--min-confidence", type=float, default=0.75)
    parser.add_argument("--out", default=str(MEDIA_ROOT / "training_export"))
    parser.add_argument(
        "--only-consumed",
        action="store_true",
        help="only export detections an operator actually picked and saved a permit "
        "against - a stronger correctness signal than OCR confidence alone, but "
        "excludes anything still sitting unused",
    )
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    db = SessionLocal()
    try:
        rows = db.query(models.DetectedPlate).order_by(models.DetectedPlate.id).all()
    finally:
        db.close()

    exported = 0
    skipped_low_confidence = 0
    skipped_no_box = 0
    skipped_not_consumed = 0
    skipped_missing_image = 0

    manifest_path = out_dir / "manifest.jsonl"
    with open(manifest_path, "w", encoding="utf-8") as manifest:
        for row in rows:
            confidence = float(row.confidence) if row.confidence is not None else None
            if confidence is None or confidence < args.min_confidence:
                skipped_low_confidence += 1
                continue
            if args.only_consumed and not row.consumed:
                skipped_not_consumed += 1
                continue
            if row.plate_box is None:
                skipped_no_box += 1
                continue

            vehicle_src = MEDIA_ROOT / row.vehicle_image_path if row.vehicle_image_path else None
            plate_src = MEDIA_ROOT / row.plate_image_path if row.plate_image_path else None
            if not vehicle_src or not vehicle_src.exists():
                skipped_missing_image += 1
                continue

            img = cv2.imread(str(vehicle_src))
            if img is None:
                skipped_missing_image += 1
                continue
            height, width = img.shape[:2]

            dest_image = out_dir / f"{row.id}.jpg"
            dest_label = out_dir / f"{row.id}.txt"
            shutil.copyfile(vehicle_src, dest_image)
            dest_label.write_text(to_yolo_line(row.plate_box, width, height) + "\n", encoding="utf-8")

            plate_copied = False
            if plate_src and plate_src.exists():
                shutil.copyfile(plate_src, out_dir / f"{row.id}_plate.jpg")
                plate_copied = True

            manifest.write(
                json.dumps(
                    {
                        "id": row.id,
                        "image": f"{row.id}.jpg",
                        "label": f"{row.id}.txt",
                        "plate_crop": f"{row.id}_plate.jpg" if plate_copied else None,
                        "plate_text": row.plate_text,
                        "short_format": row.short_format,
                        "characters": row.plate_chars,
                        "confidence": confidence,
                        "camera_id": row.camera_id,
                        "consumed": row.consumed,
                        "detected_at": row.detected_at.isoformat(),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            exported += 1

    print(f"exported {exported} detections to {out_dir}")
    print(
        f"skipped: {skipped_low_confidence} below --min-confidence, "
        f"{skipped_no_box} with no stored plate box (detected before this feature existed), "
        f"{skipped_not_consumed} not consumed (--only-consumed), "
        f"{skipped_missing_image} with a missing image file"
    )
    print(f"manifest: {manifest_path}")


if __name__ == "__main__":
    main()
