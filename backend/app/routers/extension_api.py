from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from .. import models, schemas
from ..config import ACTIVE_PLATE_WINDOW_MINUTES, PLATE_SUPPRESS_AFTER_SAVE_MINUTES
from ..database import get_db
from ..security import check_extension_api_key

router = APIRouter(
    prefix="/api",
    tags=["extension"],
    dependencies=[Depends(check_extension_api_key)],
)


@router.get("/plates/active", response_model=list[schemas.ActivePlateOut])
def active_plates(db: Session = Depends(get_db)):
    """Every not-yet-used plate detected in the last
    ACTIVE_PLATE_WINDOW_MINUTES, newest first - shown to every operator's
    extension regardless of which camera/line it came from (any operator
    may handle any line's truck).

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

    rows = (
        db.query(models.DetectedPlate)
        .join(models.Camera)
        .filter(models.DetectedPlate.consumed.is_(False))
        .filter(models.DetectedPlate.detected_at >= cutoff)
        .filter(models.Camera.is_active.is_(True))
        .order_by(models.DetectedPlate.detected_at.desc())
        .all()
    )
    def parse_confidence(value):
        try:
            return float(value) if value is not None else None
        except ValueError:
            return None

    return [
        schemas.ActivePlateOut(
            id=row.id,
            short_format=row.short_format,
            plate_text=row.plate_text,
            line_number=row.camera.line_number,
            line_name=row.camera.name,
            detected_at=row.detected_at.isoformat(),
            confidence=parse_confidence(row.confidence),
        )
        for row in rows
        if (row.camera_id, row.plate_text) not in suppressed
    ]


@router.post("/permit-logs", response_model=schemas.PermitLogOut)
def create_permit_log(payload: schemas.PermitLogIn, request: Request, db: Session = Depends(get_db)):
    log = models.PermitLog(
        detected_plate_id=payload.detected_plate_id,
        page_type=payload.page_type,
        page_url=payload.page_url,
        plate=payload.plate,
        transporter=payload.transporter,
        permit_type=payload.permit_type,
        plant=payload.plant,
        loading_point=payload.loading_point,
        vehicle=payload.vehicle,
        operator_computer_ip=request.client.host if request.client else None,
    )
    db.add(log)

    if payload.detected_plate_id is not None:
        detected = db.query(models.DetectedPlate).get(payload.detected_plate_id)
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

    db.commit()
    db.refresh(log)
    return schemas.PermitLogOut(id=log.id)
