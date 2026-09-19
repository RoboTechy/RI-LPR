"""
Build an ImageFolder-style character dataset from IR-LPR's per-character
XML annotations, for retraining the plate OCR step (image_classifier.py's
FCModel).

Each IR-LPR annotation has one "کل ناحیه پلاک" (whole plate) object -
already used by convert_annotations_to_yolo.py - plus one object per
individual plate character, where <name> is the character itself (a
digit like "7", or a Persian letter like "ن"). This script crops each
of those character boxes out of the full car image and saves it under:

    data/IR-LPR/car-image/{train,val}/chars/<character>/<xml_stem>_<i>.png

i.e. the standard torchvision.datasets.ImageFolder layout, one folder
per character/class - ready for scripts/train_char_classifier.py.

Images are matched to annotations by the xml file's own name (see
convert_annotations_to_yolo.py's docstring for why - the <filename> tag
is stale).

Crops are preprocessed (grayscale, CLAHE, Otsu threshold) to the same
"dark character on light background" binary domain that
license_plate_extractor.extract_digits() ultimately feeds the
classifier (its raw output is background/foreground-inverted for
cv2.connectedComponentsWithStats, then flipped back with `1.0 - x`
before classification - see license_Plate_Recognition_end_to_end.ipynb).
Training on a different domain than inference sees would make the
classifier's accuracy on real crops meaningless.

Usage (after scripts/download_ir_lpr.py has extracted train/ and val/):
    python scripts/convert_char_annotations.py
"""

import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "IR-LPR" / "car-image"
PLATE_LABEL = "کل ناحیه پلاک"
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")
MIN_CROP_SIZE = 4  # px, guards against degenerate annotation boxes


def preprocess_char_crop(crop_rgb: np.ndarray) -> np.ndarray:
    """Match license_plate_extractor's final classifier-input domain: binary, dark character on light background."""
    gray = cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # resize to 26x26 + 2px pad, matching extract_digits()'s digit images
    resized = cv2.resize(thresh, (26, 26), interpolation=cv2.INTER_AREA)
    return np.pad(resized, (2, 2), "constant", constant_values=255)


def parse_char_boxes(annotation_path: Path):
    """Return [(label, (x_min, y_min, x_max, y_max)), ...] for every non-plate object."""
    root = ET.parse(annotation_path).getroot()
    boxes = []
    for obj in root.findall("object"):
        name = obj.findtext("name")
        if not name or name == PLATE_LABEL:
            continue
        bnd = obj.find("bndbox")
        boxes.append((name, (
            float(bnd.findtext("xmin")),
            float(bnd.findtext("ymin")),
            float(bnd.findtext("xmax")),
            float(bnd.findtext("ymax")),
        )))
    return boxes


def convert_split(split_dir: Path) -> None:
    chars_out = split_dir / "chars"
    chars_out.mkdir(exist_ok=True)

    image_by_stem = {}
    for path in split_dir.rglob("*"):
        if chars_out in path.parents:
            continue
        if path.suffix.lower() in IMAGE_EXTENSIONS:
            image_by_stem.setdefault(path.stem, path)

    xml_files = list(split_dir.rglob("*.xml"))
    crops = skipped_files = 0
    for xml_path in xml_files:
        img_path = image_by_stem.get(xml_path.stem)
        char_boxes = parse_char_boxes(xml_path)
        if img_path is None or not char_boxes:
            skipped_files += 1
            continue

        with Image.open(img_path) as im:
            img_rgb = np.array(im.convert("RGB"))

        for i, (label, box) in enumerate(char_boxes):
            x_min, y_min, x_max, y_max = (int(round(v)) for v in box)
            if x_max - x_min < MIN_CROP_SIZE or y_max - y_min < MIN_CROP_SIZE:
                continue

            label_dir = chars_out / label.replace("/", "_")
            label_dir.mkdir(exist_ok=True)
            crop_path = label_dir / f"{xml_path.stem}_{i}.png"
            if crop_path.exists():
                continue

            crop = img_rgb[y_min:y_max, x_min:x_max]
            processed = preprocess_char_crop(crop)
            cv2.imwrite(str(crop_path), processed)
            crops += 1

    classes = sorted(p.name for p in chars_out.iterdir() if p.is_dir())
    print(f"[{split_dir.name}] {len(xml_files)} annotation files -> "
          f"{crops} character crops across {len(classes)} classes, "
          f"{skipped_files} files skipped (missing image or no character boxes)")


def main() -> None:
    for split in ("train", "val"):
        split_dir = DATA_DIR / split
        if not split_dir.exists():
            print(f"[{split}] not found, skipping (run download_ir_lpr.py first)")
            continue
        convert_split(split_dir)


if __name__ == "__main__":
    main()
