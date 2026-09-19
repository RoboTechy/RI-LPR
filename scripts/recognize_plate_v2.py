"""
End-to-end plate recognition using a single multi-class YOLO character
detector instead of classical (threshold + connected components)
segmentation followed by a separate classifier - see
scripts/convert_char_detection_dataset.py and
scripts/train_char_detector.py for why: the classical segmentation
regularly drops or merges characters on real photos.

Usage:
    python scripts/recognize_plate_v2.py car_a.jpg
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ultralytics import YOLO  # noqa: E402

from license_plate_extractor import detect_and_crop_plate  # noqa: E402

MODELS_DIR = REPO_ROOT / "models"

# Iranian plates: 2 digits, 1 letter, 3 digits, 2 digits (8 characters).
PLATE_LENGTH = 8
LETTER_POSITION = 2


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", help="path to a car photo")
    args = parser.parse_args()

    weights_path = MODELS_DIR / "ir_lpr_char_detector.pt"
    if not weights_path.exists():
        raise SystemExit(
            f"{weights_path} not found - run scripts/convert_char_detection_dataset.py "
            f"and scripts/train_char_detector.py first."
        )

    plate_crop = detect_and_crop_plate(args.image)
    char_model = YOLO(str(weights_path))
    results = char_model(plate_crop)[0]

    detections = []
    for box in results.boxes:
        x_center = box.xywh[0][0].item()
        class_name = results.names[int(box.cls[0])]
        confidence = box.conf[0].item()
        detections.append((x_center, class_name, confidence))
    detections.sort(key=lambda d: d[0])  # left to right

    plate_string = " ".join(d[1] for d in detections)
    print(f"Detected {len(detections)} characters (expected {PLATE_LENGTH})")
    print("Predicted license plate:", plate_string)

    if len(detections) == PLATE_LENGTH:
        letter = detections[LETTER_POSITION][1]
        if letter.isdigit():
            print(f"warning: position {LETTER_POSITION} (should be a letter) read as digit {letter!r}")
        digit_positions = [i for i in range(PLATE_LENGTH) if i != LETTER_POSITION]
        for i in digit_positions:
            if not detections[i][1].isdigit():
                print(f"warning: position {i} (should be a digit) read as letter {detections[i][1]!r}")


if __name__ == "__main__":
    main()
