"""
Draft license-plate bounding boxes for a folder of vehicle photos, to
speed up manual annotation (e.g. in Roboflow) when building a new
training set - reviewing/correcting a drawn box is much faster than
drawing one from scratch.

Runs the same vehicle -> plate detection used at inference
(license_plate_extractor.py's VEHICLE_CLASS_IDS + _detect_plate_box(),
including its general-purpose fallback), but keeps the plate box in the
ORIGINAL image's coordinates (not crop-relative) and writes a single-class
YOLO label ("license-plate") next to each image - the format an
annotation tool like Roboflow expects on import.

Images where a plate was found go to <output>/prelabeled/ with a .txt
label. Images where nothing was found go to <output>/needs_manual_box/
with NO label - eyeball these: draw a box by hand in Roboflow if a plate
is actually visible, otherwise discard the image.

Usage:
    python scripts/prelabel_plate_boxes.py /path/to/photos /path/to/output
"""

import argparse
import shutil
from pathlib import Path

import cv2
from ultralytics import YOLO

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from license_plate_extractor import (  # noqa: E402
    DEFAULT_PLATE_MODEL_PATH,
    VEHICLE_CLASS_IDS,
    _detect_plate_box,
    filter_boxes_by_class,
)

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")
CLASS_NAME = "license-plate"


def find_plate_box_in_full_image(image_path: Path, vehicle_model: YOLO):
    """Return (xmin, ymin, xmax, ymax) in the ORIGINAL image's pixel coordinates, or None."""
    vehicle_results = vehicle_model(str(image_path), verbose=False)
    vehicle_boxes = filter_boxes_by_class(vehicle_results[0].boxes, VEHICLE_CLASS_IDS)
    if not vehicle_boxes:
        return None
    vx1, vy1, vx2, vy2 = max(vehicle_boxes, key=lambda b: abs(b[2] - b[0]) * abs(b[3] - b[1]))

    img_bgr = cv2.imread(str(image_path))
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    cropped = img_rgb[int(vy1):int(vy2), int(vx1):int(vx2)]

    plate_box = _detect_plate_box(cropped, DEFAULT_PLATE_MODEL_PATH)
    if plate_box is None:
        return None
    px1, py1, px2, py2 = plate_box
    return (vx1 + px1, vy1 + py1, vx1 + px2, vy1 + py2)


def write_yolo_label(label_path: Path, box, image_width: int, image_height: int) -> None:
    x1, y1, x2, y2 = box
    x_center = (x1 + x2) / 2 / image_width
    y_center = (y1 + y2) / 2 / image_height
    width = (x2 - x1) / image_width
    height = (y2 - y1) / image_height
    label_path.write_text(f"0 {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", help="folder of vehicle photos (searched recursively)")
    parser.add_argument("output_dir", help="where to write prelabeled/ and needs_manual_box/")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    prelabeled_images = output_dir / "prelabeled" / "images"
    prelabeled_labels = output_dir / "prelabeled" / "labels"
    needs_review = output_dir / "needs_manual_box"
    for d in (prelabeled_images, prelabeled_labels, needs_review):
        d.mkdir(parents=True, exist_ok=True)

    (output_dir / "prelabeled" / "classes.txt").write_text(CLASS_NAME + "\n")

    vehicle_model = YOLO("yolo11n.pt")
    image_paths = [p for p in input_dir.rglob("*") if p.suffix.lower() in IMAGE_EXTENSIONS]
    print(f"found {len(image_paths)} images")

    prelabeled = needs_manual = 0
    for i, image_path in enumerate(image_paths, 1):
        box = find_plate_box_in_full_image(image_path, vehicle_model)
        img = cv2.imread(str(image_path))
        height, width = img.shape[:2]

        if box is not None:
            shutil.copy(image_path, prelabeled_images / image_path.name)
            write_yolo_label(prelabeled_labels / (image_path.stem + ".txt"), box, width, height)
            prelabeled += 1
        else:
            shutil.copy(image_path, needs_review / image_path.name)
            needs_manual += 1

        if i % 50 == 0:
            print(f"  {i}/{len(image_paths)} processed ({prelabeled} prelabeled, {needs_manual} need review)")

    print(f"done: {prelabeled} prelabeled -> {prelabeled_images.parent}, "
          f"{needs_manual} need manual review -> {needs_review}")


if __name__ == "__main__":
    main()
