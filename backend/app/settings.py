"""Tiny helpers around the AppSetting key/value table (see models.py)."""
from sqlalchemy.orm import Session

from . import models

# How long a light stays green in AUTOMATIC mode (after a permit is saved).
AUTO_GREEN_SECONDS_KEY = "auto_green_seconds"
DEFAULT_AUTO_GREEN_SECONDS = 30.0

# Per line: "auto" (a saved permit turns the light green for the time above)
# or "manual" (only an operator's green/red buttons change it).
LIGHT_MODES = ("auto", "manual")
DEFAULT_LIGHT_MODE = "auto"


def _get(db: Session, key: str):
    setting = db.query(models.AppSetting).get(key)
    return setting.value if setting is not None else None


def _set(db: Session, key: str, value: str) -> None:
    setting = db.query(models.AppSetting).get(key)
    if setting is None:
        db.add(models.AppSetting(key=key, value=value))
    else:
        setting.value = value
    db.commit()


def get_auto_green_seconds(db: Session) -> float:
    try:
        return float(_get(db, AUTO_GREEN_SECONDS_KEY))
    except (TypeError, ValueError):
        return DEFAULT_AUTO_GREEN_SECONDS


def set_auto_green_seconds(db: Session, seconds: float) -> None:
    _set(db, AUTO_GREEN_SECONDS_KEY, str(seconds))


def _mode_key(line_number: int) -> str:
    return f"light_mode_line_{line_number}"


def get_light_mode(db: Session, line_number: int) -> str:
    value = _get(db, _mode_key(line_number))
    return value if value in LIGHT_MODES else DEFAULT_LIGHT_MODE


def set_light_mode(db: Session, line_number: int, mode: str) -> None:
    if mode not in LIGHT_MODES:
        raise ValueError(mode)
    _set(db, _mode_key(line_number), mode)
