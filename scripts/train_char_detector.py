"""
Train a multi-class YOLO11 character detector on the dataset built by
scripts/convert_char_detection_dataset.py. It detects AND classifies
every character on a (already-cropped) plate image in one pass - class
names are the characters themselves (e.g. "7", "ن") - replacing the
classical threshold+connected-components segmentation and the separate
CharCNN classifier.

Usage:
    python scripts/train_char_detector.py
    python scripts/train_char_detector.py --epochs 100 --model yolo11s.pt
"""

import argparse
from pathlib import Path

from ultralytics import YOLO

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_YAML = REPO_ROOT / "data" / "IR-LPR" / "car-image" / "chars_yolo_data.yaml"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="yolo11n.pt")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=320,
                         help="plate crops are small and low-res compared to full car photos")
    parser.add_argument("--batch", type=float, default=-1)
    parser.add_argument("--name", default="ir_lpr_char_detector")
    args = parser.parse_args()

    if not DATA_YAML.exists():
        raise SystemExit(
            f"{DATA_YAML} not found - run scripts/download_ir_lpr.py and "
            f"scripts/convert_char_detection_dataset.py first."
        )

    model = YOLO(args.model)
    model.train(
        data=str(DATA_YAML),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=0,
        amp=True,
        project=str(REPO_ROOT / "runs" / "detect"),
        name=args.name,
    )


if __name__ == "__main__":
    main()
