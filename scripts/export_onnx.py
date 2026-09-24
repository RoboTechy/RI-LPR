"""
Export both trained YOLO models (plate detector + character detector) to
ONNX, for deploying on the production server (CPU-only, ~20 cores, no
GPU) without needing PyTorch/CUDA installed there at all - just
onnxruntime, a much lighter and more portable dependency for a
CPU-only box.

NOTE ON SPEED: measured on a small-model benchmark (car_a.jpg, 20 runs),
ONNX Runtime was NOT faster than plain PyTorch CPU inference here (~78ms
vs ~74ms/image) - these models are tiny (yolo11n, ~2.5M params), so
runtime overhead dominates rather than raw compute, and the usual
"ONNX is faster on CPU" assumption didn't hold. The real win here is a
lighter deployment (no torch/CUDA dependency chain on the server, which
is exactly what broke training on the dev machine's GPU driver mismatch
earlier in this project) and a portable, standard inference format - not
speed. Re-benchmark on the actual production server before assuming
either format is faster there; hardware differences can flip this.

Each model keeps its own training image size (the plate detector was
trained at 640px, the character detector at 320px - see
scripts/train_plate_detector.py and scripts/train_char_detector.py) since
an ONNX export bakes the input size into the graph.

Usage:
    python scripts/export_onnx.py
"""

from pathlib import Path

from ultralytics import YOLO

REPO_ROOT = Path(__file__).resolve().parent.parent

# (weights path, training image size)
MODELS = [
    (REPO_ROOT / "models" / "ir_lpr_plate_detector.pt", 640),
    (REPO_ROOT / "models" / "ir_lpr_char_detector.pt", 320),
]


def main() -> None:
    for weights, imgsz in MODELS:
        if not weights.exists():
            print(f"skip: {weights} not found")
            continue
        model = YOLO(str(weights))
        onnx_path = model.export(format="onnx", imgsz=imgsz, dynamic=False, simplify=True)
        print(f"exported {weights.name} -> {onnx_path}")


if __name__ == "__main__":
    main()
