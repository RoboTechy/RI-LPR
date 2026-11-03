"""
Shared helpers between camera_worker.py (continuous RTSP polling) and
test_server.py (the on-demand "تست ارتباط" endpoint the admin panel
calls) - kept in one place so both use the exact same model paths and
image-saving logic.
"""
import sys
from pathlib import Path
from uuid import uuid4

import cv2

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import MEDIA_ROOT  # noqa: E402

PLATE_MODEL_PATH = str(REPO_ROOT / "models" / "ir_lpr_plate_detector.onnx")
CHAR_MODEL_PATH = str(REPO_ROOT / "models" / "ir_lpr_char_detector.onnx")


def format_plate_short(chars):
    """Mirrors extension/content.js's formatPlateShort() - must stay in
    sync with it: strip the letter (index 2), write the remaining digits
    as "{first2+mid3}/{last2}"."""
    first5 = chars[0] + chars[1] + chars[3] + chars[4] + chars[5]
    last2 = chars[6] + chars[7]
    return f"{first5}/{last2}"


def save_image(img_rgb, subfolder):
    out_dir = MEDIA_ROOT / subfolder
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}.jpg"
    path = out_dir / filename
    bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
    # compressed - these accumulate indefinitely, keep each one small.
    cv2.imwrite(str(path), bgr, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return f"{subfolder}/{filename}"
