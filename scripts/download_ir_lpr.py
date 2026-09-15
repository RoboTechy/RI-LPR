"""
Download the IR-LPR "Car Image" dataset (Malek Ashtar University) from
Google Drive and extract it under data/IR-LPR/car-image/.

This dataset contains full car images with bounding-box annotations for
the license plate location - used to retrain the YOLO11 plate-detection
model (replacing the original ~400-image Roboflow set).

Run this LOCALLY (not in a cloud sandbox) - the files are large
(train ~8.3GB, val ~1.2GB, test ~2.3GB) and training itself needs your
GPU.

Usage:
    pip install gdown
    python scripts/download_ir_lpr.py            # train + val
    python scripts/download_ir_lpr.py --test      # also download test
    python scripts/download_ir_lpr.py --only val  # just one split
"""

import argparse
import zipfile
from pathlib import Path

import gdown

# Google Drive file IDs, from https://github.com/mut-deep/IR-LPR
CAR_IMAGE_FILES = {
    "train": "1XtZ-XQ8ImNFf40D-bFqTm0UVFqNKhbLi",
    "val": "1hwz6X-Zp7JpJL35K6P3z7k6O_PTXhUcT",
    "test": "1pe4_HgXb9dctFGJXVNlyNcKSXZeht0lX",
}

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "IR-LPR" / "car-image"


def download_split(split: str) -> Path:
    file_id = CAR_IMAGE_FILES[split]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = DATA_DIR / f"{split}.zip"
    if zip_path.exists():
        print(f"[{split}] zip already downloaded, skipping download: {zip_path}")
    else:
        print(f"[{split}] downloading...")
        gdown.download(id=file_id, output=str(zip_path), quiet=False)
    return zip_path


def extract_split(split: str, zip_path: Path) -> None:
    out_dir = DATA_DIR / split
    if out_dir.exists() and any(out_dir.iterdir()):
        print(f"[{split}] already extracted, skipping: {out_dir}")
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[{split}] extracting...")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(out_dir)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--test", action="store_true", help="also download the test split"
    )
    parser.add_argument(
        "--only", choices=["train", "val", "test"], help="download only this split"
    )
    args = parser.parse_args()

    if args.only:
        splits = [args.only]
    else:
        splits = ["train", "val"] + (["test"] if args.test else [])

    for split in splits:
        zip_path = download_split(split)
        extract_split(split, zip_path)

    print("Done. Next: inspect the extracted annotation format and run "
          "scripts/convert_annotations_to_yolo.py")


if __name__ == "__main__":
    main()
