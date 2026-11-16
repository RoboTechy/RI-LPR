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


# A line's region is where its truck's LICENSE PLATE must be (see
# detect_and_crop_plate): a vehicle is read only if a plate on it lies inside
# the region, wherever the rest of the truck is. Each outline follows the TOP
# edge of that line's jersey barriers (about 1% of the frame height above
# it), so a plate on a truck standing in front of the barriers is inside,
# and a truck on a far road or on another lane behind the barriers has its
# plate outside. Frame coordinates are normalized (x, y in 0..1) so a region
# works at either stream size. Traced from live frames, 2026-11-15/16.
LANE_REGIONS = {
    # Line 1: along the top edge of the jersey barriers (1 point margin up).
    1: (
        (0, 0.424),
        (0.1, 0.421),
        (0.3, 0.421),
        (0.5, 0.423),
        (0.65, 0.43),
        (0.8, 0.434),
        (0.9, 0.443),
        (1, 0.457),
        (1, 1),
        (0, 1),
    ),
    # Line 2: along the top of the barriers too, except a dip at x .76-.84:
    # the gap between two blocks where the plate of the truck on the next
    # lane shows through (x=.78, y=.42 in the 2026-11-16 frames) - it must
    # stay outside. A near truck's plate (x=.43, y=.345) is inside.
    2: (
        (0, 0.198),
        (0.14, 0.223),
        (0.28, 0.263),
        (0.46, 0.323),
        (0.54, 0.326),
        (0.6, 0.35),
        (0.75, 0.356),
        (0.76, 0.44),
        (0.84, 0.44),
        (0.85, 0.383),
        (1, 0.393),
        (1, 1),
        (0, 1),
    ),
    # Lines 3-6: along the top edge of the jersey barriers, about 1% of the
    # frame height above it.
    3: (
        (0, 0.308),
        (0.107, 0.314),
        (0.229, 0.335),
        (0.298, 0.352),
        (0.4, 0.376),
        (0.47, 0.378),
        (0.554, 0.434),
        (0.64, 0.449),
        (0.73, 0.478),
        (0.794, 0.466),
        (0.853, 0.485),
        (0.986, 0.529),
        (1, 0.534),
        (1, 1),
        (0, 1),
    ),
    4: (
        (0, 0.478),
        (0.032, 0.472),
        (0.123, 0.462),
        (0.2, 0.453),
        (0.267, 0.445),
        (0.357, 0.436),
        (0.5, 0.424),
        (0.576, 0.422),
        (0.672, 0.421),
        (0.78, 0.417),
        (1, 0.417),
        (1, 1),
        (0, 1),
    ),
    5: (
        (0, 0.353),
        (0.07, 0.328),
        (0.13, 0.308),
        (0.2, 0.268),
        (0.255, 0.238),
        (0.32, 0.208),
        (0.4, 0.173),
        (0.48, 0.158),
        (0.55, 0.133),
        (0.62, 0.128),
        (0.75, 0.103),
        (0.85, 0.1),
        (1, 0.1),
        (1, 1),
        (0, 1),
    ),
    6: (
        (0, 0.343),
        (0.1, 0.338),
        (0.15, 0.323),
        (0.2, 0.313),
        (0.26, 0.303),
        (0.36, 0.288),
        (0.47, 0.298),
        (0.56, 0.288),
        (0.677, 0.286),
        (0.76, 0.282),
        (0.96, 0.286),
        (1, 0.278),
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
