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


# Frame coordinates are normalized so the region works at either stream size.
# Line 2 follows the camera-side base of the separator and includes the full
# approach and stopping area visible in the 2026-11-10 vehicle samples.
#
# Line 1's camera looks across a row of jersey barriers at an unrelated
# through-road beyond them (confirmed via a live reference frame - two
# passing trucks visible on that far road, with line 1's own stopping lot
# empty in the foreground). The region below follows the top edge of that
# barrier row, excluding everything above/beyond it. Calibrated from a
# single empty-lot frame (no line 1 truck present yet to verify against) -
# generous on purpose (the whole foreground lot, full width) so it should
# safely include a real truck wherever it actually stops; re-check once a
# frame with an occupied line 1 is available.
LANE_REGIONS = {
    1: (
        (0, 0.40),
        (0.2, 0.40),
        (0.4, 0.415),
        (0.6, 0.425),
        (0.8, 0.44),
        (1, 0.46),
        (1, 1),
        (0, 1),
    ),
    2: (
        (0, 0.3),
        (0.14, 0.324),
        (0.28, 0.373),
        (0.46, 0.427),
        (0.63, 0.5),
        (0.78, 0.531),
        (0.9, 0.576),
        (1, 0.617),
        (1, 1),
        (0, 1),
    ),
}


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
