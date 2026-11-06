from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import relationship

from .database import Base


def utcnow():
    return datetime.now(timezone.utc)


user_camera_access = Table(
    "user_camera_access",
    Base.metadata,
    Column("admin_user_id", ForeignKey("admin_users.id"), primary_key=True),
    Column("camera_id", ForeignKey("cameras.id"), primary_key=True),
)


class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    # A superuser sees/manages every camera; otherwise restricted to the
    # cameras listed in `cameras` below (per-camera access, as requested).
    is_superuser = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    cameras = relationship("Camera", secondary=user_camera_access, back_populates="allowed_users")


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    # Physical gate/line number the operators know it by (1-6 today) -
    # this is what gets shown next to a detected plate in the extension.
    line_number = Column(Integer, unique=True, nullable=False)

    rtsp_ip = Column(String(100), nullable=False)
    rtsp_port = Column(Integer, default=554, nullable=False)
    rtsp_username = Column(String(100), default="", nullable=False)
    rtsp_password = Column(String(100), default="", nullable=False)
    rtsp_path = Column(String(255), default="/Streaming/Channels/101", nullable=False)
    # If set, used verbatim instead of building the URL from the fields
    # above - for cameras whose RTSP URL doesn't fit that shape.
    rtsp_url_override = Column(String(500), nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    allowed_users = relationship("AdminUser", secondary=user_camera_access, back_populates="cameras")
    detections = relationship("DetectedPlate", back_populates="camera")

    @property
    def rtsp_url(self):
        if self.rtsp_url_override:
            return self.rtsp_url_override
        auth = ""
        if self.rtsp_username:
            auth = f"{self.rtsp_username}:{self.rtsp_password}@"
        return f"rtsp://{auth}{self.rtsp_ip}:{self.rtsp_port}{self.rtsp_path}"


class DetectedPlate(Base):
    __tablename__ = "detected_plates"

    id = Column(Integer, primary_key=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False)

    # 8 single-character strings, left to right, as read_plate() returns
    # them - e.g. ["1","2","ج","3","4","5","6","7"].
    plate_chars = Column(JSON, nullable=False)
    plate_text = Column(String(20), nullable=False)       # "12ج34567"
    short_format = Column(String(20), nullable=False)      # "12345/67"
    confidence = Column(String(20), nullable=True)          # min char confidence, as text

    plate_image_path = Column(String(255), nullable=True)
    vehicle_image_path = Column(String(255), nullable=True)

    # (xmin, ymin, xmax, ymax) of the plate WITHIN vehicle_image_path -
    # i.e. where to draw/crop it on that specific image file, for
    # building fine-tuning datasets later (see
    # worker/export_training_dataset.py). Null for detections logged
    # before this field existed.
    plate_box = Column(JSON, nullable=True)

    detected_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)

    consumed = Column(Boolean, default=False, nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)

    camera = relationship("Camera", back_populates="detections")
    permit_logs = relationship("PermitLog", back_populates="detected_plate")


class PermitLog(Base):
    __tablename__ = "permit_logs"

    id = Column(Integer, primary_key=True)
    detected_plate_id = Column(Integer, ForeignKey("detected_plates.id"), nullable=True)

    page_type = Column(String(20), nullable=False)   # "shipping" | "unloading"
    page_url = Column(Text, nullable=True)

    plate = Column(String(50), nullable=True)
    transporter = Column(String(255), nullable=True)
    permit_type = Column(String(255), nullable=True)
    plant = Column(String(255), nullable=True)
    loading_point = Column(String(255), nullable=True)
    vehicle = Column(String(255), nullable=True)

    operator_computer_ip = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)

    detected_plate = relationship("DetectedPlate", back_populates="permit_logs")


class AppSetting(Base):
    """Small generic key/value store for admin-editable settings that
    don't warrant their own dedicated table/column - currently just
    manual_green_seconds (see cameras.html / admin.py)."""

    __tablename__ = "app_settings"

    key = Column(String(100), primary_key=True)
    value = Column(String(255), nullable=False)
