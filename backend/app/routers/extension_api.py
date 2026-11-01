from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from .. import models, schemas
from ..config import ACTIVE_PLATE_WINDOW_MINUTES
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
    may handle any line's truck)."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=ACTIVE_PLATE_WINDOW_MINUTES)
    rows = (
        db.query(models.DetectedPlate)
        .join(models.Camera)
        .filter(models.DetectedPlate.consumed.is_(False))
        .filter(models.DetectedPlate.detected_at >= cutoff)
        .filter(models.Camera.is_active.is_(True))
        .order_by(models.DetectedPlate.detected_at.desc())
        .all()
    )
    return [
        schemas.ActivePlateOut(
            id=row.id,
            short_format=row.short_format,
            plate_text=row.plate_text,
            line_number=row.camera.line_number,
            line_name=row.camera.name,
            detected_at=row.detected_at.isoformat(),
        )
        for row in rows
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
        if detected is not None and not detected.consumed:
            detected.consumed = True
            detected.consumed_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(log)
    return schemas.PermitLogOut(id=log.id)
