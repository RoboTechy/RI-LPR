"""
Fine-tune YOLO11 for license-plate detection on the converted IR-LPR
dataset (data/IR-LPR/car-image/data.yaml, built by
convert_annotations_to_yolo.py).

Defaults are picked for a 6GB-VRAM laptop GPU (e.g. RTX 4050): yolo11n
(the smallest variant), 640px images, and automatic batch-size selection
(Ultralytics measures free VRAM at startup and picks the largest batch
that fits at ~60% utilization) - pass --batch to override if you'd
rather set it manually.

Usage:
    python scripts/train_plate_detector.py
    python scripts/train_plate_detector.py --epochs 100 --model yolo11s.pt
    python scripts/train_plate_detector.py --batch 16 --imgsz 512
"""

import argparse
from pathlib import Path

from ultralytics import YOLO

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_YAML = REPO_ROOT / "data" / "IR-LPR" / "car-image" / "data.yaml"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model", default="yolo11n.pt",
        help="base weights to fine-tune (yolo11n.pt is smallest/fastest, "
             "good for 6GB VRAM; yolo11s.pt is the next step up)",
    )
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument(
        "--batch", type=float, default=-1,
        help="-1 = auto-select batch size from free VRAM (default)",
    )
    parser.add_argument(
        "--name", default="ir_lpr_plate_detector",
        help="run name; results land in runs/detect/<name>/",
    )
    parser.add_argument(
        "--device", default="0",
        help="'0' for first CUDA GPU (default), 'cpu' if no GPU is available "
             "or working - ultralytics does NOT fall back to CPU on its own, "
             "it errors out",
    )
    args = parser.parse_args()

    if not DATA_YAML.exists():
        raise SystemExit(
            f"{DATA_YAML} not found - run scripts/download_ir_lpr.py and "
            f"scripts/convert_annotations_to_yolo.py first."
        )

    model = YOLO(args.model)
    model.train(
        data=str(DATA_YAML),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        amp=args.device != "cpu",   # mixed precision needs a CUDA GPU
        project=str(REPO_ROOT / "runs" / "detect"),
        name=args.name,
    )


if __name__ == "__main__":
    main()
