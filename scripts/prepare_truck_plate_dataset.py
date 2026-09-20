"""
Turn the curated truck-plate set (truck_plates/raw/ - 253 real Iranian
truck photos with single-class "license-plate" boxes, produced by
scripts/prelabel_plate_boxes.py and manually reviewed/cleaned) into a
train/val split ready for Ultralytics YOLO fine-tuning, mirroring the
layout convert_annotations_to_yolo.py builds for IR-LPR.

We skip Roboflow entirely here: the images are already boxed, so there's
nothing left for a labeling tool to do - this just needs a split and a
data.yaml.

Optionally mixes a sample of IR-LPR car images into the train split too
(--mix-car-images). Fine-tuning models/ir_lpr_plate_detector.pt on 253
truck-only images for many epochs risks catastrophic forgetting of the
car case it was originally trained for; interleaving a batch of the
original car training data is the standard mitigation. Off by default
since it requires data/IR-LPR/car-image/train to already exist locally
(see the main README's "Getting the training data" section).

Usage:
    python scripts/prepare_truck_plate_dataset.py
    python scripts/prepare_truck_plate_dataset.py --mix-car-images 500
"""

import argparse
import random
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "truck_plates" / "raw"
OUT_DIR = REPO_ROOT / "data" / "truck-plates"
CAR_TRAIN_DIR = REPO_ROOT / "data" / "IR-LPR" / "car-image" / "train"
CLASS_NAMES = ["license-plate"]


def load_pairs(images_dir: Path, labels_dir: Path):
    pairs = []
    for image_path in sorted(images_dir.iterdir()):
        label_path = labels_dir / (image_path.stem + ".txt")
        if label_path.exists():
            pairs.append((image_path, label_path))
    return pairs


def write_split(pairs, images_out: Path, labels_out: Path) -> None:
    images_out.mkdir(parents=True, exist_ok=True)
    labels_out.mkdir(parents=True, exist_ok=True)
    for image_path, label_path in pairs:
        shutil.copy(image_path, images_out / image_path.name)
        shutil.copy(label_path, labels_out / label_path.name)


def mix_in_car_images(train_images_out: Path, train_labels_out: Path, count: int, seed: int) -> int:
    if not CAR_TRAIN_DIR.exists():
        print(f"--mix-car-images requested but {CAR_TRAIN_DIR} not found - skipping (run "
              f"download_ir_lpr.py + convert_annotations_to_yolo.py first if you want this)")
        return 0

    car_pairs = load_pairs(CAR_TRAIN_DIR / "images", CAR_TRAIN_DIR / "labels")
    sample = random.Random(seed).sample(car_pairs, min(count, len(car_pairs)))
    for image_path, label_path in sample:
        # car images are large (IR-LPR downloads), symlink instead of copying
        link = train_images_out / image_path.name
        if not link.exists():
            link.symlink_to(image_path.resolve())
        shutil.copy(label_path, train_labels_out / label_path.name)
    return len(sample)


def write_data_yaml() -> None:
    yaml_path = OUT_DIR / "data.yaml"
    yaml_path.write_text(
        "train: train/images\n"
        "val: val/images\n"
        f"nc: {len(CLASS_NAMES)}\n"
        f"names: {CLASS_NAMES}\n"
    )
    print(f"Wrote {yaml_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--val-ratio", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--mix-car-images", type=int, default=0,
        help="sample this many IR-LPR car images into the train split too, "
             "to reduce forgetting of cars during fine-tuning (default: 0, off)",
    )
    args = parser.parse_args()

    if not RAW_DIR.exists():
        raise SystemExit(f"{RAW_DIR} not found.")

    pairs = load_pairs(RAW_DIR / "images", RAW_DIR / "labels")
    if not pairs:
        raise SystemExit(f"No image/label pairs found under {RAW_DIR}.")

    rng = random.Random(args.seed)
    shuffled = pairs[:]
    rng.shuffle(shuffled)
    n_val = max(1, round(len(shuffled) * args.val_ratio))
    val_pairs, train_pairs = shuffled[:n_val], shuffled[n_val:]

    train_images, train_labels = OUT_DIR / "train" / "images", OUT_DIR / "train" / "labels"
    val_images, val_labels = OUT_DIR / "val" / "images", OUT_DIR / "val" / "labels"
    write_split(train_pairs, train_images, train_labels)
    write_split(val_pairs, val_images, val_labels)
    print(f"train: {len(train_pairs)} truck images, val: {len(val_pairs)} truck images")

    if args.mix_car_images:
        n_mixed = mix_in_car_images(train_images, train_labels, args.mix_car_images, args.seed)
        if n_mixed:
            print(f"train: +{n_mixed} car images mixed in ({len(train_pairs) + n_mixed} total)")

    write_data_yaml()


if __name__ == "__main__":
    main()
