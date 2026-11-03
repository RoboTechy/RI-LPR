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
from fastapi import FastAPI

from pipeline_utils import CHAR_MODEL_PATH, PLATE_MODEL_PATH, save_image

from app import models  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from license_plate_extractor import read_plate  # noqa: E402

app = FastAPI(title="RI-LPR worker internal test API")

CONNECT_TIMEOUT_SECONDS = 10


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

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name
        cv2.imwrite(tmp_path, frame)
        result = read_plate(tmp_path, char_model_path=CHAR_MODEL_PATH, plate_model_path=PLATE_MODEL_PATH)
    except Exception as exc:
        return {
            "success": True,
            "error": None,
            "ocr_success": False,
            "ocr_text": None,
            "ocr_reason": f"خطای پردازش تصویر: {exc}",
            "characters_detected": None,
            "image_path": None,
        }
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)

    annotated = result["vehicle_crop"].copy()
    if result.get("plate_box") is not None:
        x1, y1, x2, y2 = (int(v) for v in result["plate_box"])
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (255, 0, 0), 4)

    image_path = save_image(annotated, "camera_tests")

    return {
        "success": True,
        "error": None,
        "ocr_success": result["success"],
        "ocr_text": result["plate_text"],
        "ocr_reason": result["reason"],
        "characters_detected": " ".join(c for c, _conf in result["characters"]) if result["characters"] else None,
        "image_path": image_path,
    }
