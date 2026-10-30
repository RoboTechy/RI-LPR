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

from license_plate_extractor import read_plate  # noqa: E402

MODELS_DIR = REPO_ROOT / "models"


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

    result = read_plate(args.image, char_model_path=str(weights_path))

    chars_str = " ".join(c for c, _conf in result["characters"])
    print(f"Detected {len(result['characters'])} characters: {chars_str}")

    if result["success"]:
        print("Predicted license plate:", result["plate_text"])
    else:
        print(f"REJECTED (not trustworthy): {result['reason']}")
        print("-> a production worker would ask the operator to enter this plate manually")


if __name__ == "__main__":
    main()
