"""
Tiny internal HTTP API, served from inside the worker container
(alongside the camera-reading threads - see camera_worker.py's main()),
on an address only reachable from other containers on the same Docker
Compose network, never published to the host.

Backs the admin panel's per-camera "تست ارتباط" button: the api
container (which deliberately has none of the heavy ML dependencies -
see backend/Dockerfile vs Dockerfile.worker) calls this one endpoint
over the Compose network (http://worker:9000) instead of running
inference itself.
"""
import tempfile
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path

import cv2
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from pipeline_utils import CHAR_MODEL_PATH, PLATE_MODEL_PATH, format_plate_short, save_image

from app import models  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from license_plate_extractor import read_plate  # noqa: E402

app = FastAPI(title="RI-LPR worker internal test API")

CONNECT_TIMEOUT_SECONDS = 10
STREAM_JPEG_QUALITY = 60


def _grab_one_frame(rtsp_url):
    """Connects and reads a single frame, abandoned after
    CONNECT_TIMEOUT_SECONDS - cv2.VideoCapture can otherwise hang far
    longer than that against an unreachable camera, which would make one
    bad camera freeze this admin-facing test for everyone."""

    def _do():
        cap = cv2.VideoCapture(rtsp_url)
        if not cap.isOpened():
            cap.release()
            return None
        ok, frame = cap.read()
        cap.release()
        return frame if ok else None

    # Not a `with` block on purpose: its __exit__ calls shutdown(wait=True),
    # which would block here until the still-hung _do() finally returns -
    # exactly what the timeout below is trying to avoid. shutdown(wait=False)
    # lets this function return on time; the orphaned thread is left to
    # finish (or hang) on its own, an acceptable cost for an infrequent
    # manual "test connection" click.
    ex = ThreadPoolExecutor(max_workers=1)
    future = ex.submit(_do)
    try:
        return future.result(timeout=CONNECT_TIMEOUT_SECONDS)
    except FutureTimeoutError:
        return None
    finally:
        ex.shutdown(wait=False)


@app.post("/test-camera/{camera_id}")
def test_camera(camera_id: int):
    db = SessionLocal()
    try:
        camera = db.query(models.Camera).get(camera_id)
        if camera is None:
            return {"success": False, "error": "دوربین پیدا نشد"}
        rtsp_url = camera.rtsp_url
    finally:
        db.close()

    frame = _grab_one_frame(rtsp_url)
    if frame is None:
        return {"success": False, "error": "اتصال به دوربین برقرار نشد یا تصویری دریافت نشد"}

    # Always show the live frame, even with no truck in it right now -
    # only draw boxes on it when something was actually found. RGB to
    # match what read_plate() draws its boxes' coordinates against
    # (detect_and_crop_plate() works in RGB throughout).
    annotated = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    ocr_success = False
    ocr_text = None
    short_format = None
    ocr_reason = None
    characters_detected = None

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name
        cv2.imwrite(tmp_path, frame)
        result = read_plate(tmp_path, char_model_path=CHAR_MODEL_PATH, plate_model_path=PLATE_MODEL_PATH)
    except ValueError as exc:
        # expected/common case: no truck (or no plate on it) in this
        # particular frame - not a real error, just nothing to draw.
        ocr_reason = str(exc)
        result = None
    except Exception as exc:
        ocr_reason = f"خطای پردازش تصویر: {exc}"
        result = None
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)

    if result is not None:
        GREEN = (0, 255, 0)  # annotated is RGB, so this really is green
        vx1, vy1, vx2, vy2 = (int(v) for v in result["vehicle_box"])
        cv2.rectangle(annotated, (vx1, vy1), (vx2, vy2), GREEN, 3)
        if result.get("plate_box") is not None:
            px1, py1, px2, py2 = (int(v) for v in result["plate_box"])
            cv2.rectangle(annotated, (px1, py1), (px2, py2), GREEN, 3)
        ocr_success = result["success"]
        ocr_text = result["plate_text"]
        ocr_reason = result["reason"]
        characters_detected = " ".join(c for c, _conf in result["characters"]) if result["characters"] else None
        if ocr_success:
            # The same short, letter-stripped "XXXXX/XX" format the
            # operator actually sees in Rahkaran (extension overlay) -
            # show that here too instead of the raw 8-character OCR
            # dump, so what's shown on this test page matches reality.
            short_format = format_plate_short([c for c, _conf in result["characters"]])

    image_path = save_image(annotated, "camera_tests")

    return {
        "success": True,
        "error": None,
        "ocr_success": ocr_success,
        "ocr_text": ocr_text,
        "short_format": short_format,
        "ocr_reason": ocr_reason,
        "characters_detected": characters_detected,
        "image_path": image_path,
    }


@app.get("/stream-camera/{camera_id}")
def stream_camera(camera_id: int):
    """Raw MJPEG passthrough (no inference - just the live feed, so it
    stays cheap even while an admin leaves this open) for the "why isn't
    this live" complaint about the test page only showing a snapshot per
    click. A second, independent RTSP connection from the one
    camera_loop() keeps open for actual detection - most cameras handle
    a couple of concurrent viewers fine for a short admin session."""
    db = SessionLocal()
    try:
        camera = db.query(models.Camera).get(camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="camera not found")
        rtsp_url = camera.rtsp_url
    finally:
        db.close()

    def generate():
        cap = cv2.VideoCapture(rtsp_url)
        if not cap.isOpened():
            cap.release()
            return
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                ok2, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, STREAM_JPEG_QUALITY])
                if not ok2:
                    continue
                yield (
                    b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                    + str(len(buf)).encode()
                    + b"\r\n\r\n"
                    + buf.tobytes()
                    + b"\r\n"
                )
        finally:
            cap.release()

    return StreamingResponse(generate(), media_type="multipart/x-mixed-replace; boundary=frame")
