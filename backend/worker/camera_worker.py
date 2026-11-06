"""
Continuously reads each active camera's RTSP stream, runs the plate
pipeline (read_plate() from license_plate_extractor.py, using the
exported ONNX models for CPU-only inference) on a frame every
WORKER_POLL_INTERVAL_SECONDS, and inserts a DetectedPlate row (plus
saves the plate/vehicle crop images) whenever a read succeeds and it
looks like a DIFFERENT truck than the one last logged on that camera -
see box_iou() and camera_loop()'s same_truck check for how "different"
is decided. A time-based cooldown alone isn't enough: a truck can sit
at a line for well over any reasonable cooldown, and should still only
ever produce one active entry the whole time it's there.

A vehicle still counts as "present" (keeping the tracked position/entry
alive) even on a frame where its plate specifically couldn't be read -
e.g. someone briefly walking in front of just the plate - as opposed to
a frame where no vehicle was found at all; only the latter counts
toward WORKER_PRESENCE_GAP_SECONDS. Otherwise a person obstructing the
plate for longer than that gap would make a still-parked truck look
like it had left and a new one arrived, re-logging it.

Also runs test_server's tiny internal HTTP API (the admin panel's
per-camera "تست ارتباط" button) in the main thread, alongside these
camera-reading loops in daemon background threads - see test_server.py.

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

import cv2
import uvicorn

from pipeline_utils import (  # noqa: E402
    CHAR_MODEL_PATH,
    PLATE_MODEL_PATH,
    REPO_ROOT,
    format_plate_short,
    save_image,
)

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

from license_plate_extractor import read_plate  # noqa: E402

from app import models, relay_client  # noqa: E402
from app.config import (  # noqa: E402
    WORKER_IOU_SAME_TRUCK_THRESHOLD,
    WORKER_POLL_INTERVAL_SECONDS,
    WORKER_PRESENCE_GAP_SECONDS,
)
from app.database import Base, SessionLocal, engine  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(threadName)s] %(message)s")
log = logging.getLogger(__name__)


def box_iou(box1, box2):
    """Intersection-over-union of two (xmin, ymin, xmax, ymax) boxes -
    how much two reads' vehicle positions overlap, as a 0..1 fraction."""
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area1 = max(0.0, box1[2] - box1[0]) * max(0.0, box1[3] - box1[1])
    area2 = max(0.0, box2[2] - box2[0]) * max(0.0, box2[3] - box2[1])
    union = area1 + area2 - intersection
    return intersection / union if union > 0 else 0.0


def store_detection(camera_id, chars, plate_text, result):
    """Inserts a new DetectedPlate row and returns its id."""
    short_format = format_plate_short(chars)
    plate_image_path = save_image(result["plate_crop"], "plates")
    vehicle_image_path = save_image(result["vehicle_crop"], "vehicles")
    confidences = [conf for _c, conf in result["characters"]]
    min_confidence = min(confidences) if confidences else None

    # result's boxes are in the ORIGINAL frame's coordinates - translate
    # the plate box into vehicle_image_path's own coordinate space (i.e.
    # relative to vehicle_crop, since that's the file it's saved
    # alongside) for later fine-tuning exports (see
    # worker/export_training_dataset.py).
    vx1, vy1, _vx2, _vy2 = result["vehicle_box"]
    px1, py1, px2, py2 = result["plate_box"]
    plate_box_local = [px1 - vx1, py1 - vy1, px2 - vx1, py2 - vy1]

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
            plate_box=plate_box_local,
            detected_at=datetime.now(timezone.utc),
        )
        db.add(detection)
        db.commit()
        db.refresh(detection)
        log.info("logged plate %s (short: %s) on camera %s", plate_text, short_format, camera_id)
        return detection.id
    finally:
        db.close()


def touch_detection(detection_id):
    """Refreshes detected_at on an existing (not-yet-consumed) row - the
    same truck is still sitting there, so it shouldn't age out of
    ACTIVE_PLATE_WINDOW_MINUTES and silently vanish from the extension's
    list while someone is still working on getting to it."""
    db = SessionLocal()
    try:
        detection = db.query(models.DetectedPlate).get(detection_id)
        if detection is not None and not detection.consumed:
            detection.detected_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


def camera_loop(camera_id: int):
    # Position of the vehicle in the last SUCCESSFUL read on this camera,
    # and when that was - used to recognize "still the same truck" by
    # where it sits in frame rather than by time or exact plate text
    # (both proved unreliable - see this file's module docstring).
    last_vehicle_box = None
    last_seen_at = 0.0
    last_detection_id = None

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
                vehicle_still_present = False  # a vehicle was found this frame, even if its plate wasn't readable
                try:
                    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                        tmp_path = tmp.name
                    cv2.imwrite(tmp_path, frame)
                    result = read_plate(
                        tmp_path, char_model_path=CHAR_MODEL_PATH, plate_model_path=PLATE_MODEL_PATH
                    )
                    # detect_and_crop_plate() only raises before this point
                    # (see below) - reaching here means a vehicle (and a
                    # plate box within it) was found, whether or not the
                    # characters on it were readable.
                    vehicle_still_present = True
                except ValueError as exc:
                    result = None
                    # "No license plate detected..." means a vehicle WAS
                    # found - someone briefly standing in front of just the
                    # plate (the reported case) still leaves the vehicle
                    # itself visible. Only "No cars or trucks detected"
                    # means there's really nothing there. Distinguishing
                    # matters here: treating the first case as "gone" would
                    # let the presence-gap timer below expire during a
                    # person simply walking past, re-logging the same
                    # still-parked truck as if it were a new one.
                    vehicle_still_present = "No license plate detected" in str(exc)
                except Exception:
                    log.exception("read_plate() failed on a frame from line %s", line_number)
                    result = None
                finally:
                    if tmp_path:
                        Path(tmp_path).unlink(missing_ok=True)

                now = time.monotonic()

                # Departure check - runs on every poll regardless of what
                # this particular frame found, so a truck that drives off
                # and is simply never detected again still gets noticed
                # promptly (on the first poll past the gap), not only
                # reactively whenever something later happens to be
                # detected. Also turns that line's light back red, but
                # only if it's green because of an automatic (Save-
                # triggered) trigger - never interrupts a manual test
                # someone in the admin panel is running (see
                # relay_client.set_light_red_if_auto()).
                if last_vehicle_box is not None and (now - last_seen_at) > WORKER_PRESENCE_GAP_SECONDS:
                    last_vehicle_box = None
                    last_detection_id = None
                    relay_client.set_light_red_if_auto(line_number)

                if vehicle_still_present:
                    vehicle_box = result["vehicle_box"] if result else last_vehicle_box
                    same_truck = (
                        last_vehicle_box is not None
                        and vehicle_box is not None
                        and box_iou(vehicle_box, last_vehicle_box) >= WORKER_IOU_SAME_TRUCK_THRESHOLD
                    )
                    if not same_truck:
                        # tracking a new candidate position - nothing
                        # logged for it yet, so there's nothing to touch
                        # until a successful read confirms it (invariant:
                        # last_detection_id is only ever set for a
                        # detection whose position matches last_vehicle_box).
                        last_detection_id = None

                    if result and result["success"]:
                        chars = [c for c, _conf in result["characters"]]
                        plate_text = "".join(chars)
                        if last_detection_id is not None:
                            touch_detection(last_detection_id)
                        else:
                            last_detection_id = store_detection(camera_id, chars, plate_text, result)
                    elif last_detection_id is not None:
                        # vehicle confirmed still in the same spot, but no
                        # trustworthy plate text this frame (occluded,
                        # unreadable, ...) - nothing new to log, just keep
                        # the existing entry from aging out.
                        touch_detection(last_detection_id)

                    if vehicle_box is not None:
                        last_vehicle_box = vehicle_box
                    last_seen_at = now

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

    for camera_id in camera_ids:
        threading.Thread(target=camera_loop, args=(camera_id,), name=f"camera-{camera_id}", daemon=True).start()

    # the per-camera connection-test API the admin panel calls - runs in
    # the main thread (blocks here), camera loops above keep running as
    # daemon threads for as long as this process is alive.
    from test_server import app  # noqa: E402 - imported here so its own sys.path setup doesn't race camera_loop's

    log.info("starting internal test-connection API on :9000")
    uvicorn.run(app, host="0.0.0.0", port=9000, log_level="warning")


if __name__ == "__main__":
    main()
