from datetime import datetime, timedelta, timezone
from unicodedata import decimal

import httpx
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session, aliased

from .. import models, relay_client, schemas
from ..settings import get_auto_green_seconds, get_light_mode
from ..config import ACTIVE_PLATE_WINDOW_MINUTES, PLATE_SUPPRESS_AFTER_SAVE_MINUTES, WORKER_INTERNAL_URL
from ..database import get_db
from ..security import check_extension_api_key

router = APIRouter(
    prefix="/api",
    tags=["extension"],
    dependencies=[Depends(check_extension_api_key)],
)


@router.get("/plates/active", response_model=list[schemas.ActivePlateOut])
def active_plates(db: Session = Depends(get_db)):
    """Return the latest detection per active line if it is still eligible.

    A consumed or expired latest detection leaves the line empty. An older
    truck must not reappear after the latest truck's permit is saved.

    Also excludes any plate whose exact text was already used on a saved
    permit (same camera) within the last PLATE_SUPPRESS_AFTER_SAVE_MINUTES
    - without this, a truck still sitting at the same line keeps getting
    freshly detected and reappears in the list right after being saved."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=ACTIVE_PLATE_WINDOW_MINUTES)
    suppress_cutoff = datetime.now(timezone.utc) - timedelta(minutes=PLATE_SUPPRESS_AFTER_SAVE_MINUTES)

    recently_consumed = (
        db.query(models.DetectedPlate.camera_id, models.DetectedPlate.plate_text)
        .filter(models.DetectedPlate.consumed.is_(True))
        .filter(models.DetectedPlate.consumed_at >= suppress_cutoff)
        .distinct()
        .all()
    )
    suppressed = {(camera_id, plate_text) for camera_id, plate_text in recently_consumed}

    newer = aliased(models.DetectedPlate)
    has_newer_detection = (
        db.query(newer.id)
        .filter(
            newer.camera_id == models.DetectedPlate.camera_id,
            newer.id > models.DetectedPlate.id,
        )
        .exists()
    )
    rows = (
        db.query(models.DetectedPlate)
        .join(models.Camera)
        .filter(~has_newer_detection)
        .filter(models.DetectedPlate.consumed.is_(False))
        .filter(models.DetectedPlate.detected_at >= cutoff)
        .filter(models.Camera.is_active.is_(True))
        .order_by(models.DetectedPlate.id.desc())
        .all()
    )
    def parse_confidence(value):
        try:
            return float(value) if value is not None else None
        except ValueError:
            return None

    result = []
    for row in rows:
        if (row.camera_id, row.plate_text) in suppressed:
            continue
        result.append(
            schemas.ActivePlateOut(
                id=row.id,
                short_format=row.short_format,
                plate_text=row.plate_text,
                line_number=row.camera.line_number,
                line_name=row.camera.name,
                detected_at=row.detected_at.isoformat(),
                confidence=parse_confidence(row.confidence),
            )
        )
    return result


def hidden_plate_reason(db, detection_id):
    detection = db.get(models.DetectedPlate, detection_id) if detection_id is not None else None
    if detection is None:
        return "updating"
    if detection.consumed:
        return "permit_saved"

    same_camera = db.query(models.DetectedPlate.id).filter(
        models.DetectedPlate.camera_id == detection.camera_id
    )
    if same_camera.filter(models.DetectedPlate.id > detection.id).first():
        return "newer_detection"

    now = datetime.now(timezone.utc)
    suppress_cutoff = now - timedelta(minutes=PLATE_SUPPRESS_AFTER_SAVE_MINUTES)
    if same_camera.filter(
        models.DetectedPlate.plate_text == detection.plate_text,
        models.DetectedPlate.consumed.is_(True),
        models.DetectedPlate.consumed_at >= suppress_cutoff,
    ).first():
        return "permit_recent"

    cutoff = now - timedelta(minutes=ACTIVE_PLATE_WINDOW_MINUTES)
    if same_camera.filter(
        models.DetectedPlate.id == detection.id,
        models.DetectedPlate.detected_at < cutoff,
    ).first():
        return "expired"
    return "updating"


@router.get("/plates/overlay")
def plate_overlay(db: Session = Depends(get_db)):
    cameras = (
        db.query(models.Camera.id, models.Camera.line_number, models.Camera.is_active)
        .order_by(models.Camera.line_number)
        .all()
    )
    db.rollback()
    try:
        response = httpx.get(f"{WORKER_INTERNAL_URL}/lane-status", timeout=0.7)
        response.raise_for_status()
        states = response.json()
    except (httpx.HTTPError, ValueError):
        states = {}

    candidates = {plate.line_number: plate for plate in active_plates(db)}
    plates = []
    lanes = []
    for camera_id, line_number, enabled in cameras:
        state = states.get(str(camera_id), {})
        status = state.get("status", "unavailable") if enabled else "disabled"
        lane = {"line_number": line_number, "status": status}
        if status == "detected":
            plate = candidates.get(line_number)
            detection_id = state.get("detection_id")
            if plate is not None and plate.id == detection_id:
                plates.append(plate)
                lane["status"] = "available"
            else:
                lane["status"] = "not_available"
                lane["reason"] = hidden_plate_reason(db, detection_id)
        lanes.append(lane)
    return {"plates": plates, "lanes": lanes}


@router.post("/plates/reread/{line_number}")
def reread_plate(line_number: int, db: Session = Depends(get_db)):
    camera_id = (
        db.query(models.Camera.id)
        .filter(models.Camera.line_number == line_number, models.Camera.is_active.is_(True))
        .scalar()
    )
    db.rollback()  # release the database connection while the worker reads the stream
    if camera_id is None:
        return {"status": "unavailable"}
    try:
        response = httpx.post(f"{WORKER_INTERNAL_URL}/reread-plate/{camera_id}", timeout=11)
        response.raise_for_status()
        read = response.json()
    except (httpx.HTTPError, ValueError):
        return {"status": "unavailable"}

    if read.get("status") in ("busy", "empty", "no_read"):
        return {"status": read["status"]}
    if read.get("status") != "read":
        return {"status": "unavailable"}
    visible = any(
        plate.id == read.get("detection_id") and plate.line_number == line_number
        for plate in active_plates(db)
    )
    if visible:
        return {"status": "available"}
    return {"status": "not_available", "reason": hidden_plate_reason(db, read.get("detection_id"))}


def plate_digits(value):
    return "".join(str(decimal(char)) for char in (value or "") if char.isdecimal())


def classify_plate_source(payload, selected, db):
    # Older extension versions never sent a display observation.
    if "shown_plate_detection_id" not in payload.model_fields_set:
        return None, None

    number = plate_digits(payload.plate)
    if len(number) != 7:
        return None, None
    if payload.detected_plate_id is not None:
        if selected is None:
            return None, None
        source = "selected" if plate_digits(selected.short_format) == number else "selected_edited"
        return source, None

    if payload.shown_plate_detection_id is not None:
        shown = db.get(models.DetectedPlate, payload.shown_plate_detection_id)
        if shown is not None and plate_digits(shown.short_format) == number:
            return "manual_shown", shown.id

    if any(plate_digits(plate.short_format) == number for plate in active_plates(db)):
        return "manual_detected", None
    return "manual_no_detection", None


@router.post("/permit-logs", response_model=schemas.PermitLogOut)
def create_permit_log(payload: schemas.PermitLogIn, request: Request, db: Session = Depends(get_db)):
    detected = (
        db.get(models.DetectedPlate, payload.detected_plate_id)
        if payload.detected_plate_id is not None else None
    )
    plate_source, shown_id = classify_plate_source(payload, detected, db)
    log = models.PermitLog(
        plate_source=plate_source,
        shown_plate_detection_id=shown_id,
        detected_plate_id=payload.detected_plate_id,
        page_type=payload.page_type,
        page_url=payload.page_url,
        plate=payload.plate,
        transporter=payload.transporter,
        transporter_national_code=payload.transporter_national_code,
        permit_type=payload.permit_type,
        plant=payload.plant,
        loading_point=payload.loading_point,
        vehicle=payload.vehicle,
        operator_computer_ip=request.client.host if request.client else None,
    )
    db.add(log)

    line_number_to_light = None

    if detected is not None:
        now = datetime.now(timezone.utc)
        if not detected.consumed:
            detected.consumed = True
            detected.consumed_at = now

        # Also consume any other not-yet-used detections of the exact
        # same plate on the same camera (e.g. near-duplicate rows from
        # the same truck read a few polls apart) - otherwise they'd
        # still show up right after this one gets saved.
        siblings = (
            db.query(models.DetectedPlate)
            .filter(models.DetectedPlate.camera_id == detected.camera_id)
            .filter(models.DetectedPlate.plate_text == detected.plate_text)
            .filter(models.DetectedPlate.consumed.is_(False))
            .all()
        )
        for sibling in siblings:
            sibling.consumed = True
            sibling.consumed_at = now

        line_number_to_light = detected.camera.line_number

    db.commit()
    db.refresh(log)

    if line_number_to_light is not None:
        # Best-effort (see relay_client.py) - a relay/network hiccup must
        # never fail saving the permit, which already succeeded above.
        # Only in AUTOMATIC mode: the light goes green for the admin-set
        # time and the Pi turns it red again itself. A line set to MANUAL
        # is left alone - its operator controls the light.
        if get_light_mode(db, line_number_to_light) == "auto":
            relay_client.set_light(line_number_to_light, "green", seconds=get_auto_green_seconds(db))

    return schemas.PermitLogOut(id=log.id)
