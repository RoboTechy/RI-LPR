"""
Continuously reads each active camera's RTSP stream, runs the plate
pipeline (read_plate() from license_plate_extractor.py, using the
exported ONNX models for CPU-only inference) on a frame every
WORKER_POLL_INTERVAL_SECONDS, and inserts a DetectedPlate row (plus
saves the plate/vehicle crop images) whenever a read succeeds and it
isn't the same plate already logged for that camera within the last
WORKER_DEDUPE_COOLDOWN_SECONDS - a parked truck would otherwise get
re-logged on every single poll.

Runs as its own container (see ../docker-compose.yml), separate from
the FastAPI app, so a stuck/unreachable camera can't affect the API or
admin panel.
"""
import logging
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import cv2

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

from license_plate_extractor import read_plate  # noqa: E402

from app import models  # noqa: E402
from app.config import (  # noqa: E402
    MEDIA_ROOT,
    WORKER_DEDUPE_COOLDOWN_SECONDS,
    WORKER_POLL_INTERVAL_SECONDS,
)
from app.database import Base, SessionLocal, engine  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(threadName)s] %(message)s")
log = logging.getLogger(__name__)

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
    filename = f"{uuid4().hex}.jpg"
    path = MEDIA_ROOT / subfolder / filename
    bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
    # compressed - these accumulate indefinitely, keep each one small.
    cv2.imwrite(str(path), bgr, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return f"{subfolder}/{filename}"


def store_detection(camera_id, chars, plate_text, result):
    short_format = format_plate_short(chars)
    plate_image_path = save_image(result["plate_crop"], "plates")
    vehicle_image_path = save_image(result["vehicle_crop"], "vehicles")
    confidences = [conf for _c, conf in result["characters"]]
    min_confidence = min(confidences) if confidences else None

    db = SessionLocal()
    try:
        detection = models.DetectedPlate(
            camera_id=camera_id,
            plate_chars=chars,
            plate_text=plate_text,
            short_format=short_format,
            confidence=f"{min_confidence:.3f}" if min_confidence is not None else None,
            plate_image_path=plate_image_path,
            vehicle_image_path=vehicle_image_path,
            detected_at=datetime.now(timezone.utc),
        )
        db.add(detection)
        db.commit()
        log.info("logged plate %s (short: %s) on camera %s", plate_text, short_format, camera_id)
    finally:
        db.close()


def camera_loop(camera_id: int):
    last_plate_text = None
    last_plate_at = 0.0

    while True:
        db = SessionLocal()
        try:
            camera = db.query(models.Camera).get(camera_id)
            if camera is None or not camera.is_active:
                log.info("camera %s no longer active, stopping its loop", camera_id)
                return
            rtsp_url = camera.rtsp_url
            line_number = camera.line_number
        finally:
            db.close()

        cap = cv2.VideoCapture(rtsp_url)
        if not cap.isOpened():
            log.warning("could not open RTSP stream for line %s - retrying in 10s", line_number)
            cap.release()
            time.sleep(10)
            continue

        log.info("connected to line %s", line_number)
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    log.warning("lost connection to line %s - reconnecting", line_number)
                    break

                tmp_path = None
                try:
                    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                        tmp_path = tmp.name
                    cv2.imwrite(tmp_path, frame)
                    result = read_plate(
                        tmp_path, char_model_path=CHAR_MODEL_PATH, plate_model_path=PLATE_MODEL_PATH
                    )
                except Exception:
                    log.exception("read_plate() failed on a frame from line %s", line_number)
                    result = None
                finally:
                    if tmp_path:
                        Path(tmp_path).unlink(missing_ok=True)

                if result and result["success"]:
                    chars = [c for c, _conf in result["characters"]]
                    plate_text = "".join(chars)
                    now = time.monotonic()
                    if plate_text != last_plate_text or (now - last_plate_at) > WORKER_DEDUPE_COOLDOWN_SECONDS:
                        store_detection(camera_id, chars, plate_text, result)
                        last_plate_text = plate_text
                        last_plate_at = now

                time.sleep(WORKER_POLL_INTERVAL_SECONDS)
        finally:
            cap.release()

        time.sleep(5)  # brief pause before reconnecting


def main():
    Base.metadata.create_all(bind=engine)  # idempotent - in case this starts before the API container

    db = SessionLocal()
    try:
        camera_ids = [c.id for c in db.query(models.Camera).filter(models.Camera.is_active.is_(True)).all()]
    finally:
        db.close()

    if not camera_ids:
        log.warning("no active cameras configured yet - add them from the admin panel, then restart this worker")

    threads = []
    for camera_id in camera_ids:
        t = threading.Thread(target=camera_loop, args=(camera_id,), name=f"camera-{camera_id}", daemon=True)
        t.start()
        threads.append(t)

    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
