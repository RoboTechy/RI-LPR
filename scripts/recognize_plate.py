"""
End-to-end demo: detect the plate, segment its characters, and read them
with the IR-LPR-retrained classifier.

Usage:
    python scripts/recognize_plate.py car_a.jpg
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from image_classifier import CharCNN, ImageClassifier  # noqa: E402
from license_plate_extractor import extract_digits  # noqa: E402

MODELS_DIR = REPO_ROOT / "models"

# Iranian plates: 2 digits, 1 letter, 3 digits, 2 digits (8 characters,
# left to right) - e.g. 12 الف 345 67. Restricting each position to the
# character types actually legal there rules out misreads like a digit
# where only a letter can appear.
PLATE_LENGTH = 8
LETTER_POSITION = 2


def allowed_classes_for(position: int, class_names: list) -> list:
    is_letter_position = position == LETTER_POSITION
    return [c for c in class_names if c.isdigit() != is_letter_position]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", help="path to a car photo")
    parser.add_argument("--debug", action="store_true", help="save intermediate step images")
    args = parser.parse_args()

    weights_path = MODELS_DIR / "ir_lpr_char_classifier.pt"
    classes_path = MODELS_DIR / "ir_lpr_char_classifier_classes.json"
    if not weights_path.exists() or not classes_path.exists():
        raise SystemExit(
            f"{weights_path} / {classes_path} not found - run "
            f"scripts/convert_char_annotations.py and "
            f"scripts/train_char_classifier.py first."
        )
    class_names = json.loads(classes_path.read_text())
    classifier = ImageClassifier(str(weights_path), class_names, model_class=CharCNN)

    digits, _ = extract_digits(args.image, debug=args.debug, show=False, prefix=Path(args.image).stem)

    use_layout_constraint = len(digits) == PLATE_LENGTH
    if not use_layout_constraint:
        print(f"warning: segmented {len(digits)} characters, expected {PLATE_LENGTH} - "
              f"skipping position-based constraints")

    predicted = []
    for i, digit in enumerate(digits):
        allowed = allowed_classes_for(i, class_names) if use_layout_constraint else None
        predicted.append(classifier.predict(1.0 - digit, allowed_classes=allowed))
    print("Predicted license plate:", " ".join(predicted))


if __name__ == "__main__":
    main()
