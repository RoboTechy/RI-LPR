"""
Continue training the existing plate detector (models/ir_lpr_plate_detector.pt,
already fine-tuned on IR-LPR's ~14.7k passenger-car photos) on the curated
truck-plate set (data/truck-plates/, built by
scripts/prepare_truck_plate_dataset.py) - not training a new model from
base yolo11n.pt weights.

Differences from scripts/train_plate_detector.py (which does the
from-base-weights training), tuned for continuing an already-converged
model on a much smaller dataset (253 truck images vs 14671 car images):

  - starts from models/ir_lpr_plate_detector.pt, not yolo11n.pt
  - lower initial learning rate (--lr0, default 0.001 vs Ultralytics'
    usual ~0.01) so the truck-only batches don't overwrite what the
    model already learned about plates in one or two aggressive steps
  - fewer default epochs (--epochs, default 40 vs 50) - 253 images is a
    small dataset, and overfitting arrives faster than on 14671
  - --freeze lets you optionally freeze the first N backbone layers
    (0 = none frozen, the default). Freezing more of the backbone leaves
    less of the network free to drift away from the car-plate features
    it already learned; try e.g. --freeze 10 if validating on the
    original car set afterward shows regression.

IMPORTANT: this OVERWRITES what the model knows only in the direction the
new data points it, so always compare against the car val set afterward
(data/IR-LPR/car-image/data.yaml, via `model.val()` or
train_plate_detector.py's own val split) before replacing
models/ir_lpr_plate_detector.pt with this run's weights - if car accuracy
drops noticeably, re-run with --mix-car-images set when preparing the
dataset, and/or a higher --freeze.

Usage:
    python scripts/prepare_truck_plate_dataset.py   # once, to build data/truck-plates/
    python scripts/finetune_truck_plate_detector.py
    python scripts/finetune_truck_plate_detector.py --epochs 60 --freeze 10
"""

import argparse
from pathlib import Path

from ultralytics import YOLO

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_YAML = REPO_ROOT / "data" / "truck-plates" / "data.yaml"
DEFAULT_WEIGHTS = REPO_ROOT / "models" / "ir_lpr_plate_detector.pt"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--weights", default=str(DEFAULT_WEIGHTS),
        help="checkpoint to continue training from (default: the car-trained plate detector)",
    )
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument(
        "--batch", type=float, default=-1,
        help="-1 = auto-select batch size from free VRAM (default)",
    )
    parser.add_argument(
        "--lr0", type=float, default=0.001,
        help="initial learning rate - kept low since we're continuing an "
             "already-converged model, not training from scratch",
    )
    parser.add_argument(
        "--optimizer", default="AdamW",
        help="must be a concrete optimizer, not ultralytics' 'auto' default - "
             "'auto' silently ignores --lr0 and picks its own",
    )
    parser.add_argument(
        "--freeze", type=int, default=0,
        help="freeze this many leading backbone layers (0 = none, default); "
             "try e.g. 10 if fine-tuning regresses car-plate accuracy",
    )
    parser.add_argument(
        "--name", default="truck_plate_finetune",
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
            f"{DATA_YAML} not found - run scripts/prepare_truck_plate_dataset.py first."
        )
    if not Path(args.weights).exists():
        raise SystemExit(f"{args.weights} not found.")

    model = YOLO(args.weights)
    model.train(
        data=str(DATA_YAML),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        optimizer=args.optimizer,
        lr0=args.lr0,
        freeze=args.freeze if args.freeze > 0 else None,
        device=args.device,
        amp=args.device != "cpu",   # mixed precision needs a CUDA GPU
        project=str(REPO_ROOT / "runs" / "detect"),
        name=args.name,
    )

    print(
        "\nDone. Before replacing models/ir_lpr_plate_detector.pt, check this "
        "run didn't regress on cars:\n"
        "  python -c \"from ultralytics import YOLO; "
        f"YOLO('runs/detect/{args.name}/weights/best.pt').val(data='data/IR-LPR/car-image/data.yaml')\"\n"
        "If car metrics hold up, then:\n"
        f"  cp runs/detect/{args.name}/weights/best.pt models/ir_lpr_plate_detector.pt"
    )


if __name__ == "__main__":
    main()
