"""
Convert IR-LPR "Car Image" Pascal-VOC-style XML annotations into
YOLO-format labels (one <image>.txt per image, lines:
"<class> <x_center> <y_center> <width> <height>", normalized 0-1) so the
extracted dataset can be fed straight into ultralytics YOLO11 training.

IR-LPR annotation format (confirmed from a sample file):

    <annotation>
      <filename>927.jpg</filename>
      <object>
        <name>کل ناحیه پلاک</name>            <!-- whole plate region -->
        <bndbox><xmin>627</xmin><ymin>770</ymin><xmax>780</xmax><ymax>816</ymax></bndbox>
      </object>
      <object>
        <name>7</name>                          <!-- individual plate character -->
        <bndbox>...</bndbox>
      </object>
      ...
      <folder>true_all_images</folder>
    </annotation>

This script only uses the "کل ناحیه پلاک" (whole plate) box to build a
single-class plate-detection dataset. The per-character boxes are also
in the XML and could be used later to build a character-detection
dataset for retraining the OCR step, but that's out of scope here.

Usage (after scripts/download_ir_lpr.py has extracted train/ and val/):
    python scripts/convert_annotations_to_yolo.py
"""

import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "IR-LPR" / "car-image"

PLATE_LABEL = "کل ناحیه پلاک"
CLASS_NAMES = ["license-plate"]
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")


def parse_annotation_file(annotation_path: Path):
    """Return (image_filename, [(x_min, y_min, x_max, y_max), ...]) for the whole-plate box(es)."""
    root = ET.parse(annotation_path).getroot()
    image_filename = root.findtext("filename")
    boxes = []
    for obj in root.findall("object"):
        if obj.findtext("name") != PLATE_LABEL:
            continue
        bnd = obj.find("bndbox")
        boxes.append((
            float(bnd.findtext("xmin")),
            float(bnd.findtext("ymin")),
            float(bnd.findtext("xmax")),
            float(bnd.findtext("ymax")),
        ))
    return image_filename, boxes


def to_yolo_line(class_id: int, box, image_width: int, image_height: int) -> str:
    x_min, y_min, x_max, y_max = box
    x_center = (x_min + x_max) / 2 / image_width
    y_center = (y_min + y_max) / 2 / image_height
    width = (x_max - x_min) / image_width
    height = (y_max - y_min) / image_height
    return f"0 {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}"


def write_data_yaml() -> None:
    yaml_path = DATA_DIR / "data.yaml"
    yaml_path.write_text(
        "train: train/images\n"
        "val: val/images\n"
        f"nc: {len(CLASS_NAMES)}\n"
        f"names: {CLASS_NAMES}\n"
    )
    print(f"Wrote {yaml_path}")


def convert_split(split_dir: Path) -> None:
    images_out = split_dir / "images"
    labels_out = split_dir / "labels"
    images_out.mkdir(exist_ok=True)
    labels_out.mkdir(exist_ok=True)

    # Index every image once by filename (annotations live in a different
    # folder than images inside the IR-LPR zip, e.g. "true_all_images/").
    image_index = {}
    for path in split_dir.rglob("*"):
        if images_out in path.parents:
            continue
        if path.suffix.lower() in IMAGE_EXTENSIONS:
            image_index[path.name] = path

    xml_files = [p for p in split_dir.rglob("*.xml")]
    converted = skipped = 0
    for xml_path in xml_files:
        image_filename, boxes = parse_annotation_file(xml_path)
        img_path = image_index.get(image_filename)
        if img_path is None or not boxes:
            skipped += 1
            continue

        with Image.open(img_path) as im:
            width, height = im.size

        link_path = images_out / image_filename
        if not link_path.exists():
            link_path.symlink_to(img_path.resolve())

        label_path = labels_out / (Path(image_filename).stem + ".txt")
        lines = [to_yolo_line(0, box, width, height) for box in boxes]
        label_path.write_text("\n".join(lines) + "\n")
        converted += 1

    print(f"[{split_dir.name}] {len(xml_files)} annotation files -> "
          f"{converted} converted, {skipped} skipped (missing image or no plate box)")


def main() -> None:
    for split in ("train", "val"):
        split_dir = DATA_DIR / split
        if not split_dir.exists():
            print(f"[{split}] not found, skipping (run download_ir_lpr.py first)")
            continue
        convert_split(split_dir)

    write_data_yaml()


if __name__ == "__main__":
    main()
