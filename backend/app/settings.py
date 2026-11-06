"""Tiny helpers around the AppSetting key/value table (see models.py)."""
from sqlalchemy.orm import Session

from . import models

MANUAL_GREEN_SECONDS_KEY = "manual_green_seconds"
DEFAULT_MANUAL_GREEN_SECONDS = 20.0


def get_manual_green_seconds(db: Session) -> float:
    setting = db.query(models.AppSetting).get(MANUAL_GREEN_SECONDS_KEY)
    if setting is None:
        return DEFAULT_MANUAL_GREEN_SECONDS
    try:
        return float(setting.value)
    except ValueError:
        return DEFAULT_MANUAL_GREEN_SECONDS


def set_manual_green_seconds(db: Session, seconds: float) -> None:
    setting = db.query(models.AppSetting).get(MANUAL_GREEN_SECONDS_KEY)
    if setting is None:
        db.add(models.AppSetting(key=MANUAL_GREEN_SECONDS_KEY, value=str(seconds)))
    else:
        setting.value = str(seconds)
    db.commit()
