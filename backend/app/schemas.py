from typing import Optional

from pydantic import BaseModel


class ActivePlateOut(BaseModel):
    id: int
    short_format: str
    plate_text: str
    line_number: int
    line_name: str
    detected_at: str  # ISO 8601


class PermitLogIn(BaseModel):
    detected_plate_id: Optional[int] = None
    page_type: str  # "shipping" | "unloading"
    page_url: Optional[str] = None
    plate: Optional[str] = None
    transporter: Optional[str] = None
    permit_type: Optional[str] = None
    plant: Optional[str] = None
    loading_point: Optional[str] = None
    vehicle: Optional[str] = None


class PermitLogOut(BaseModel):
    id: int
