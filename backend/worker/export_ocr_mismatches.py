"""
Finds what the plate pipeline gets WRONG, using data the system already
records - the counterpart of export_training_dataset.py, which only
exports reads the pipeline was confident about.

Run on demand inside the running worker container:

    docker compose exec worker python3 backend/worker/export_ocr_mismatches.py

Two sources:

1. Saved permits. The plate an operator saved is the truth; the plate
   the camera read is the prediction. Every saved permit (with a
   7-digit plate) lands in one category:

     confirmed          picked from the list, saved unchanged - OCR right
     ocr_error          picked from the list, then corrected by up to
                        --max-diff digits - OCR wrong, and we know how
     different_plate    picked from the list, saved as something else
                        entirely - a wrong pick, not an OCR error
     manual_exact       typed by hand, but a detection with the same
                        digits existed - OCR right, operator didn't use it
     manual_near_match  typed by hand, and a detection up to --max-diff
                        digits off existed within --window-minutes before
                        the save - a probable OCR error
     manual_unmatched   typed by hand, nothing similar detected - the
                        pipeline most likely never read this truck

   The saved plate has no letter (Rahkaran's format is digits only), so
   only the 7 digits are verified. The letter in a corrected label is
   the OCR's own and is marked unverified.

2. Failed reads (the failed_reads table, filled by camera_worker.py):
   frames where a vehicle was in the lane but no plate was found, or a
   plate was found but its characters failed the format check.

Writes into --out (default media/ocr_review/):

  summary.json       counts per category, per line, digit accuracy,
                     failed reads per stage and reason
  confusion.csv      read_as,truth,count - which digit is mistaken for which
  mismatches.jsonl   one line per ocr_error / manual_near_match: OCR text,
                     corrected characters, which positions differ, the
                     per-character boxes when stored, image paths
  confirmed.jsonl    one line per confirmed / manual_exact read - verified
                     correct, usable as training data as-is
  failed_reads.jsonl one line per failed read
  images/            copies of the plate/vehicle/frame images behind
                     mismatches and failed reads, for review (--no-copy
                     to skip)

Image paths in the .jsonl files are relative to the media folder.
"""
import argparse
import csv
import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unicodedata import decimal

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app import models  # noqa: E402
from app.config import MEDIA_ROOT  # noqa: E402
from app.database import SessionLocal  # noqa: E402

# Where each of the 7 saved digits sits among the 8 plate characters
# (index 2 is the letter) - the inverse of format_plate_short().
DIGIT_POSITIONS = (0, 1, 3, 4, 5, 6, 7)


def plate_digits(value):
    return "".join(str(decimal(char)) for char in (value or "") if char.isdecimal())


def differing(a, b):
    return [i for i in range(7) if a[i] != b[i]]


def detection_record(detection):
    return {
        "detection_id": detection.id,
        "line_number": detection.camera.line_number,
        "detected_at": detection.detected_at.isoformat(),
        "ocr_chars": detection.plate_chars,
        "ocr_short_format": detection.short_format,
        "confidence": detection.confidence,
        "char_boxes": detection.char_boxes,
        "plate_image": detection.plate_image_path,
        "vehicle_image": detection.vehicle_image_path,
        "plate_box": detection.plate_box,
    }


def corrected_chars(detection, true_digits):
    chars = list(detection.plate_chars)
    for digit, position in zip(true_digits, DIGIT_POSITIONS):
        chars[position] = digit
    return chars


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(MEDIA_ROOT / "ocr_review"))
    parser.add_argument("--max-diff", type=int, default=2,
                        help="most digits that may differ for a correction to count as an OCR error")
    parser.add_argument("--window-minutes", type=int, default=60,
                        help="how far before a hand-typed permit to look for a similar detection")
    parser.add_argument("--since-days", type=int, default=None, help="only look at the last N days")
    parser.add_argument("--no-copy", action="store_true", help="write the reports only, copy no images")
    args = parser.parse_args()

    out_dir = Path(args.out)
    images_dir = out_dir / "images"
    out_dir.mkdir(parents=True, exist_ok=True)
    since = datetime.now(timezone.utc) - timedelta(days=args.since_days) if args.since_days else None

    def copy_image(relative_path, name):
        if args.no_copy or not relative_path:
            return
        source = MEDIA_ROOT / relative_path
        if source.exists():
            images_dir.mkdir(exist_ok=True)
            shutil.copyfile(source, images_dir / name)

    categories = Counter()
    per_line = defaultdict(Counter)
    confusion = Counter()
    position_errors = Counter()
    mismatches = []
    confirmed = []

    def add_mismatch(category, log, detection, true_digits):
        ocr_digits = plate_digits(detection.short_format)
        wrong = differing(ocr_digits, true_digits)
        for i in wrong:
            confusion[(ocr_digits[i], true_digits[i])] += 1
            position_errors[DIGIT_POSITIONS[i]] += 1
        record = detection_record(detection)
        record.update({
            "category": category,
            "permit_log_id": log.id,
            "saved_plate": log.plate,
            "corrected_chars": corrected_chars(detection, true_digits),
            "letter_verified": False,
            "wrong_positions": [DIGIT_POSITIONS[i] for i in wrong],
        })
        mismatches.append(record)
        copy_image(detection.plate_image_path, f"mismatch_{detection.id}_plate.jpg")
        copy_image(detection.vehicle_image_path, f"mismatch_{detection.id}_vehicle.jpg")

    def add_confirmed(category, log, detection):
        record = detection_record(detection)
        record.update({"category": category, "permit_log_id": log.id, "letter_verified": False})
        confirmed.append(record)

    db = SessionLocal()
    try:
        logs = db.query(models.PermitLog).order_by(models.PermitLog.id)
        if since:
            logs = logs.filter(models.PermitLog.created_at >= since)

        for log in logs:
            true_digits = plate_digits(log.plate)
            if len(true_digits) != 7:
                categories["skipped_no_plate"] += 1
                continue

            detection = log.detected_plate
            if detection is not None:
                ocr_digits = plate_digits(detection.short_format)
                diff = len(differing(ocr_digits, true_digits)) if len(ocr_digits) == 7 else 7
                if diff == 0:
                    category = "confirmed"
                    add_confirmed(category, log, detection)
                elif diff <= args.max_diff:
                    category = "ocr_error"
                    add_mismatch(category, log, detection, true_digits)
                else:
                    category = "different_plate"
                line = detection.camera.line_number
            else:
                # Hand-typed: was there a detection it could have come from?
                candidates = (
                    db.query(models.DetectedPlate)
                    .filter(models.DetectedPlate.detected_at >= log.created_at - timedelta(minutes=args.window_minutes))
                    .filter(models.DetectedPlate.detected_at <= log.created_at + timedelta(minutes=1))
                    .order_by(models.DetectedPlate.detected_at.desc())
                    .all()
                )
                best = None
                for candidate in candidates:
                    digits = plate_digits(candidate.short_format)
                    if len(digits) != 7:
                        continue
                    diff = len(differing(digits, true_digits))
                    if diff <= args.max_diff and (best is None or diff < best[0]):
                        best = (diff, candidate)
                if best is None:
                    category, line = "manual_unmatched", None
                elif best[0] == 0:
                    category, line = "manual_exact", best[1].camera.line_number
                    add_confirmed(category, log, best[1])
                else:
                    category, line = "manual_near_match", best[1].camera.line_number
                    add_mismatch(category, log, best[1], true_digits)

            categories[category] += 1
            if line is not None:
                per_line[line][category] += 1

        failed_query = db.query(models.FailedRead).order_by(models.FailedRead.id)
        if since:
            failed_query = failed_query.filter(models.FailedRead.created_at >= since)
        failed_reads = []
        failed_by_stage = Counter()
        failed_by_line = defaultdict(Counter)
        failed_reasons = Counter()
        for failed in failed_query:
            line = failed.camera.line_number
            failed_by_stage[failed.stage] += 1
            failed_by_line[line][failed.stage] += 1
            failed_reasons[failed.reason] += 1
            failed_reads.append({
                "failed_read_id": failed.id,
                "line_number": line,
                "created_at": failed.created_at.isoformat(),
                "stage": failed.stage,
                "reason": failed.reason,
                "characters": failed.characters,
                "plate_image": failed.plate_image_path,
                "vehicle_image": failed.vehicle_image_path,
                "frame_image": failed.frame_image_path,
                "plate_box": failed.plate_box,
            })
            copy_image(failed.plate_image_path, f"failed_{failed.id}_plate.jpg")
            copy_image(failed.vehicle_image_path, f"failed_{failed.id}_vehicle.jpg")
            copy_image(failed.frame_image_path, f"failed_{failed.id}_frame.jpg")
    finally:
        db.close()

    def write_jsonl(name, rows):
        with open(out_dir / name, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    write_jsonl("mismatches.jsonl", mismatches)
    write_jsonl("confirmed.jsonl", confirmed)
    write_jsonl("failed_reads.jsonl", failed_reads)

    with open(out_dir / "confusion.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["read_as", "truth", "count"])
        for (read_as, truth), count in confusion.most_common():
            writer.writerow([read_as, truth, count])

    ocr_right = categories["confirmed"] + categories["manual_exact"]
    ocr_wrong = categories["ocr_error"] + categories["manual_near_match"]
    judged = ocr_right + ocr_wrong
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "since_days": args.since_days,
        "permits_by_category": dict(categories),
        "permits_by_line": {str(line): dict(counts) for line, counts in sorted(per_line.items())},
        # of the permits where a detection can be compared with the saved plate
        "plate_accuracy": round(ocr_right / judged, 4) if judged else None,
        "plates_judged": judged,
        "wrong_digit_by_plate_position": {str(p): position_errors[p] for p in DIGIT_POSITIONS},
        "failed_reads_by_stage": dict(failed_by_stage),
        "failed_reads_by_line": {str(line): dict(counts) for line, counts in sorted(failed_by_line.items())},
        "failed_read_reasons": dict(failed_reasons.most_common()),
    }
    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if confusion:
        print("\nmost common digit confusions (read as -> truth):")
        for (read_as, truth), count in confusion.most_common(10):
            print(f"  {read_as} -> {truth}: {count}")
    print(f"\nwritten to {out_dir}")


if __name__ == "__main__":
    main()
