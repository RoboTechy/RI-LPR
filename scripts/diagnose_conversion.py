"""
One-off diagnostic: figure out WHY convert_annotations_to_yolo.py is
skipping almost everything. Prints, for the train split:
  - how many xml files have an object whose <name> matches "کل ناحیه پلاک"
    exactly, vs. how many have some other, near-identical label (to catch
    invisible-character / spelling variants)
  - how many of those referenced images were actually found on disk
  - a few example mismatches

Usage: python scripts/diagnose_conversion.py
"""

import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "IR-LPR" / "car-image"
PLATE_LABEL = "کل ناحیه پلاک"
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")


def main() -> None:
    split_dir = DATA_DIR / "train"
    images_out = split_dir / "images"

    image_index = {}
    for path in split_dir.rglob("*"):
        if images_out.exists() and images_out in path.parents:
            continue
        if path.suffix.lower() in IMAGE_EXTENSIONS:
            image_index[path.name] = path

    print(f"Indexed {len(image_index)} image files under {split_dir}")

    xml_files = list(split_dir.rglob("*.xml"))
    print(f"Found {len(xml_files)} xml files")

    label_counter = Counter()
    exact_label_matches = 0
    images_found_for_exact = 0
    example_label_variants = []
    example_missing_images = []

    for xml_path in xml_files[:5000]:  # sample first 5000 for speed
        root = ET.parse(xml_path).getroot()
        image_filename = root.findtext("filename")
        names = [obj.findtext("name") for obj in root.findall("object")]

        plate_like = [n for n in names if n and ("ناحیه" in n or "پلاک" in n)]
        for n in plate_like:
            label_counter[n] += 1
            if n != PLATE_LABEL and len(example_label_variants) < 5:
                example_label_variants.append((xml_path.name, repr(n)))

        if PLATE_LABEL in names:
            exact_label_matches += 1
            if image_filename in image_index:
                images_found_for_exact += 1
            elif len(example_missing_images) < 5:
                example_missing_images.append((xml_path.name, image_filename))

    print(f"\n--- Results (sampled first {min(5000, len(xml_files))} xml files) ---")
    print(f"xml files with an object whose name == {PLATE_LABEL!r} exactly: {exact_label_matches}")
    print(f"  of those, referenced image found on disk: {images_found_for_exact}")
    print(f"\nAll plate-like labels seen (name containing 'ناحیه' or 'پلاک') and their counts:")
    for label, count in label_counter.most_common(20):
        print(f"  {count:6d}  {label!r}")

    if example_label_variants:
        print(f"\nExample xml files with a DIFFERENT plate-like label (not exact match):")
        for fname, label in example_label_variants:
            print(f"  {fname}: {label}")

    if example_missing_images:
        print(f"\nExample xml files with exact label match but image NOT found on disk:")
        for xml_name, img_name in example_missing_images:
            print(f"  {xml_name} -> looked for image {img_name!r}")


if __name__ == "__main__":
    main()
