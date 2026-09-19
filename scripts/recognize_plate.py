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

from image_classifier import ImageClassifier  # noqa: E402
from license_plate_extractor import extract_digits  # noqa: E402

MODELS_DIR = REPO_ROOT / "models"


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
    classifier = ImageClassifier(str(weights_path), class_names)

    digits, _ = extract_digits(args.image, debug=args.debug, show=False, prefix=Path(args.image).stem)

    predicted = [classifier.predict(1.0 - digit) for digit in digits]
    print("Predicted license plate:", " ".join(predicted))


if __name__ == "__main__":
    main()
