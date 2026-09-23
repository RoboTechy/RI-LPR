"""
Run the plate detector on its own validation split and save an annotated
copy of every image where a real plate was missed (a false negative), so
you can eyeball what those failures have in common - dirty plates, a
specific truck type, glare, etc. - before deciding what new photos are
actually worth collecting (see the "does more data even help" discussion
in the project chat: if failures cluster around one condition, targeted
photos of that condition beat more photos of trucks that already work).

Ground truth boxes are read from data/truck-plates/val/labels/ (built by
prepare_truck_plate_dataset.py); predictions come from running the given
weights on data/truck-plates/val/images/. A ground-truth box counts as
"found" if any prediction overlaps it at IoU >= --iou-thresh (0.5 by
default, matching mAP50's own threshold).

Usage:
    python scripts/inspect_val_failures.py
    python scripts/inspect_val_failures.py --weights runs/detect/truck_plate_finetune_v3/weights/best.pt
"""

import argparse
from pathlib import Path

import cv2
from ultralytics import YOLO

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WEIGHTS = REPO_ROOT / "models" / "ir_lpr_plate_detector.pt"
DEFAULT_DATA = REPO_ROOT / "data" / "truck-plates" / "data.yaml"


def load_gt_boxes(label_path: Path, width: int, height: int):
    if not label_path.exists():
        return []
    boxes = []
    for line in label_path.read_text().strip().splitlines():
        if not line.strip():
            continue
        _, xc, yc, w, h = line.split()
        xc, yc, w, h = float(xc) * width, float(yc) * height, float(w) * width, float(h) * height
        boxes.append((xc - w / 2, yc - h / 2, xc + w / 2, yc + h / 2))
    return boxes


def iou(box_a, box_b) -> float:
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter == 0.0:
        return 0.0
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    return inter / (area_a + area_b - inter)


def draw_box(img, box, color, label):
    x1, y1, x2, y2 = (int(v) for v in box)
    cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
    cv2.putText(img, label, (x1, max(0, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--weights", default=str(DEFAULT_WEIGHTS))
    parser.add_argument("--data", default=str(DEFAULT_DATA), help="data.yaml built by prepare_truck_plate_dataset.py")
    parser.add_argument("--conf", type=float, default=0.25, help="detection confidence threshold")
    parser.add_argument("--iou-thresh", type=float, default=0.5, help="IoU to count a prediction as matching a ground-truth box")
    parser.add_argument("--output", default=str(REPO_ROOT / "val_failures"))
    args = parser.parse_args()

    data_yaml = Path(args.data)
    val_images_dir = data_yaml.parent / "val" / "images"
    val_labels_dir = data_yaml.parent / "val" / "labels"
    if not val_images_dir.exists():
        raise SystemExit(f"{val_images_dir} not found - run prepare_truck_plate_dataset.py first.")

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    model = YOLO(args.weights)

    image_paths = sorted(p for p in val_images_dir.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    total_gt = matched_gt = 0
    missed_images = []

    for image_path in image_paths:
        img = cv2.imread(str(image_path))
        height, width = img.shape[:2]
        gt_boxes = load_gt_boxes(val_labels_dir / (image_path.stem + ".txt"), width, height)
        result = model.predict(str(image_path), conf=args.conf, verbose=False)[0]
        pred_boxes = [tuple(b) for b in result.boxes.xyxy.cpu().numpy().tolist()] if len(result.boxes) else []

        unmatched_gt = []
        for gt_box in gt_boxes:
            total_gt += 1
            if any(iou(gt_box, pred_box) >= args.iou_thresh for pred_box in pred_boxes):
                matched_gt += 1
            else:
                unmatched_gt.append(gt_box)

        if unmatched_gt:
            missed_images.append(image_path.name)
            annotated = img.copy()
            for gt_box in unmatched_gt:
                draw_box(annotated, gt_box, (0, 200, 0), "missed plate (ground truth)")
            for pred_box in pred_boxes:
                draw_box(annotated, pred_box, (0, 0, 255), "predicted")
            cv2.imwrite(str(output_dir / image_path.name), annotated)

    print(f"Ground-truth plate instances: {total_gt}")
    print(f"Found (IoU >= {args.iou_thresh}): {matched_gt}")
    print(f"Missed: {total_gt - matched_gt}")
    if missed_images:
        print(f"\nImages with at least one missed plate ({len(missed_images)}), annotated copies in {output_dir}/:")
        for name in missed_images:
            print(f"  {name}")
    else:
        print("\nNo misses - every ground-truth plate in val was found.")


if __name__ == "__main__":
    main()
