"""
Build a multi-class YOLO detection dataset for reading plate characters
directly - replacing the classical (threshold + connected components)
segmentation in license_plate_extractor.py, which regularly drops or
merges characters on real photos (e.g. found only 7/8 on a test image).

Unlike scripts/convert_char_annotations.py (which crops characters out
of the FULL car image, for the separate CharCNN classifier), this script
crops the PLATE region first, then writes YOLO detection labels for the
individual character boxes relative to that crop - because at inference
time the character detector will run on the already-cropped plate (from
ir_lpr_plate_detector.pt), not the full photo, and characters are much
bigger relative to a plate-sized crop than a full car photo.

One YOLO model then both LOCATES and CLASSIFIES every character in a
single pass (class = the character itself, e.g. "7" or "ن"), so no
separate classifier or fragile segmentation step is needed downstream.

Output layout (standard Ultralytics detection dataset):
    data/IR-LPR/car-image/{train,val}/chars_yolo/images/<xml_stem>.jpg
    data/IR-LPR/car-image/{train,val}/chars_yolo/labels/<xml_stem>.txt
    data/IR-LPR/car-image/chars_yolo_data.yaml

Usage (after scripts/download_ir_lpr.py has extracted train/ and val/):
    python scripts/convert_char_detection_dataset.py
"""

import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "IR-LPR" / "car-image"
PLATE_LABEL = "کل ناحیه پلاک"
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")


def parse_annotation(xml_path: Path):
    """Return (plate_box, [(label, box), ...]) - box = (xmin, ymin, xmax, ymax). plate_box is None if absent."""
    root = ET.parse(xml_path).getroot()
    plate_box = None
    char_boxes = []
    for obj in root.findall("object"):
        name = obj.findtext("name")
        bnd = obj.find("bndbox")
        box = (
            float(bnd.findtext("xmin")),
            float(bnd.findtext("ymin")),
            float(bnd.findtext("xmax")),
            float(bnd.findtext("ymax")),
        )
        if name == PLATE_LABEL:
            plate_box = box
        elif name:
            char_boxes.append((name, box))
    return plate_box, char_boxes


def index_images_by_stem(split_dir: Path, exclude_dir: Path) -> dict:
    index = {}
    for path in split_dir.rglob("*"):
        if exclude_dir in path.parents:
            continue
        if path.suffix.lower() in IMAGE_EXTENSIONS:
            index.setdefault(path.stem, path)
    return index


def collect_classes(split_dirs) -> list:
    classes = set()
    for split_dir in split_dirs:
        for xml_path in split_dir.rglob("*.xml"):
            _, char_boxes = parse_annotation(xml_path)
            classes.update(label for label, _ in char_boxes)
    return sorted(classes)


def convert_split(split_dir: Path, class_to_idx: dict) -> None:
    out_dir = split_dir / "chars_yolo"
    images_out = out_dir / "images"
    labels_out = out_dir / "labels"
    images_out.mkdir(parents=True, exist_ok=True)
    labels_out.mkdir(parents=True, exist_ok=True)

    image_by_stem = index_images_by_stem(split_dir, out_dir)
    xml_files = list(split_dir.rglob("*.xml"))
    converted = skipped = 0

    for xml_path in xml_files:
        img_path = image_by_stem.get(xml_path.stem)
        plate_box, char_boxes = parse_annotation(xml_path)
        if img_path is None or plate_box is None or not char_boxes:
            skipped += 1
            continue

        px_min, py_min, px_max, py_max = plate_box
        plate_w, plate_h = px_max - px_min, py_max - py_min
        if plate_w <= 0 or plate_h <= 0:
            skipped += 1
            continue

        with Image.open(img_path) as im:
            crop = im.crop(plate_box).convert("RGB")

        lines = []
        for label, (x_min, y_min, x_max, y_max) in char_boxes:
            # translate to plate-crop-relative coords, clip to the crop
            cx_min = max(0.0, x_min - px_min)
            cy_min = max(0.0, y_min - py_min)
            cx_max = min(plate_w, x_max - px_min)
            cy_max = min(plate_h, y_max - py_min)
            if cx_max <= cx_min or cy_max <= cy_min:
                continue  # char box fell entirely outside the plate box

            x_center = (cx_min + cx_max) / 2 / plate_w
            y_center = (cy_min + cy_max) / 2 / plate_h
            width = (cx_max - cx_min) / plate_w
            height = (cy_max - cy_min) / plate_h
            class_id = class_to_idx[label]
            lines.append(f"{class_id} {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}")

        if not lines:
            skipped += 1
            continue

        crop.save(images_out / f"{xml_path.stem}.jpg")
        (labels_out / f"{xml_path.stem}.txt").write_text("\n".join(lines) + "\n")
        converted += 1

    print(f"[{split_dir.name}] {len(xml_files)} annotation files -> "
          f"{converted} plate crops converted, {skipped} skipped "
          f"(missing image/plate box, or no character boxes)")


def write_data_yaml(classes: list) -> None:
    yaml_path = DATA_DIR / "chars_yolo_data.yaml"
    yaml_path.write_text(
        "train: train/chars_yolo/images\n"
        "val: val/chars_yolo/images\n"
        f"nc: {len(classes)}\n"
        f"names: {classes}\n"
    )
    print(f"Wrote {yaml_path}")


def main() -> None:
    split_dirs = [DATA_DIR / split for split in ("train", "val") if (DATA_DIR / split).exists()]
    if not split_dirs:
        raise SystemExit("no train/val dirs found - run scripts/download_ir_lpr.py first")

    classes = collect_classes(split_dirs)
    class_to_idx = {cls: i for i, cls in enumerate(classes)}
    print(f"{len(classes)} character classes: {classes}")

    for split_dir in split_dirs:
        convert_split(split_dir, class_to_idx)

    write_data_yaml(classes)


if __name__ == "__main__":
    main()
