"""
Convert IR-LPR "Car Image" annotations into YOLO-format label files
(one <image>.txt per image, with lines: "<class> <x_center> <y_center>
<width> <height>", all normalized 0-1) so the extracted dataset can be
fed straight into ultralytics YOLO11 training.

INCOMPLETE ON PURPOSE: the exact annotation format shipped inside the
IR-LPR zip files (e.g. plain text, XML/Pascal VOC, COCO JSON) isn't known
until the zips are downloaded and inspected - the IR-LPR GitHub repo only
hosts the Google Drive links, not the files themselves. After running
download_ir_lpr.py:

    1. Look at data/IR-LPR/car-image/train/ and note the annotation
       file format next to the images.
    2. Fill in `parse_annotation_file()` below to read one annotation
       file and return the plate bounding box(es) in
       (x_min, y_min, x_max, y_max) pixel coordinates.
    3. Run this script to generate YOLO .txt labels + a data.yaml
       pointing ultralytics at data/IR-LPR/car-image/{train,val}.
"""

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "IR-LPR" / "car-image"

# Single class: license plate
CLASS_NAMES = ["license-plate"]


def parse_annotation_file(annotation_path: Path, image_width: int, image_height: int):
    """
    Return a list of (x_min, y_min, x_max, y_max) plate boxes, in pixel
    coordinates, for the given annotation file.

    TODO: implement once the real annotation format is known (see module
    docstring).
    """
    raise NotImplementedError(
        "Inspect data/IR-LPR/car-image/train/ after downloading and "
        "implement this based on the actual annotation format."
    )


def to_yolo_line(class_id: int, box, image_width: int, image_height: int) -> str:
    x_min, y_min, x_max, y_max = box
    x_center = (x_min + x_max) / 2 / image_width
    y_center = (y_min + y_max) / 2 / image_height
    width = (x_max - x_min) / image_width
    height = (y_max - y_min) / image_height
    return f"{class_id} {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}"


def write_data_yaml() -> None:
    yaml_path = DATA_DIR / "data.yaml"
    yaml_path.write_text(
        "train: train/images\n"
        "val: val/images\n"
        f"nc: {len(CLASS_NAMES)}\n"
        f"names: {CLASS_NAMES}\n"
    )
    print(f"Wrote {yaml_path}")


def main() -> None:
    for split in ("train", "val"):
        split_dir = DATA_DIR / split
        if not split_dir.exists():
            print(f"[{split}] not found, skipping (run download_ir_lpr.py first)")
            continue
        print(f"[{split}] converting annotations... (implement parse_annotation_file first)")
        # TODO: iterate images in split_dir, call parse_annotation_file(),
        # write YOLO .txt labels next to (or under a labels/) folder.

    write_data_yaml()


if __name__ == "__main__":
    main()
