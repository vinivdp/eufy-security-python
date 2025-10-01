"""Event data models"""

from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field


class BaseEvent(BaseModel):
    """Base event model"""
    event: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    device_sn: Optional[str] = None


class MotionDetectedEvent(BaseEvent):
    """Motion detected event"""
    event: Literal["motion_detected"] = "motion_detected"
    device_sn: str


class MotionStoppedEvent(BaseEvent):
    """Motion stopped event"""
    event: Literal["motion_stopped"] = "motion_stopped"
    device_sn: str
    duration_seconds: int


class LowBatteryEvent(BaseEvent):
    """Low battery event"""
    event: Literal["low_battery"] = "low_battery"
    device_sn: str
    battery_level: Optional[int] = None


class CameraOfflineEvent(BaseEvent):
    """Camera offline event"""
    event: Literal["camera_offline"] = "camera_offline"
    device_sn: str
    reason: Optional[str] = None


class SystemErrorEvent(BaseEvent):
    """System error event"""
    event: Literal["system_error"] = "system_error"
    operation: str
    error_type: str
    error_message: str
    retry_count: int
    context: dict
    traceback: Optional[str] = None