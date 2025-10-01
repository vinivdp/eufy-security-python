"""Event data models"""

from datetime import datetime
from typing import Optional, Literal, Any
from pydantic import BaseModel, Field
from zoneinfo import ZoneInfo

BRASILIA_TZ = ZoneInfo("America/Sao_Paulo")


def get_brasilia_now() -> datetime:
    """Get current datetime in Brasília timezone"""
    return datetime.now(BRASILIA_TZ)


class BaseEvent(BaseModel):
    """Base event model with Brasília timezone"""
    event: str
    timestamp: datetime = Field(default_factory=get_brasilia_now)
    device_sn: Optional[str] = None
    slack_channel: Optional[str] = None


class MotionDetectedEvent(BaseEvent):
    """Motion detected event"""
    event: Literal["motion_detected"] = "motion_detected"
    device_sn: str
    slack_channel: str
    state: str  # "open" or "closed"
    latest_activity: datetime
    device_name: Optional[str] = None
    event_type: Optional[str] = None
    raw_event: Optional[dict[str, Any]] = None  # Full WS event data


class MotionStoppedEvent(BaseEvent):
    """Motion stopped event (timeout-based)"""
    event: Literal["motion_stopped"] = "motion_stopped"
    device_sn: str
    slack_channel: str
    state: Literal["closed"] = "closed"  # Always closed after timeout
    duration_seconds: int
    latest_activity: datetime


class LowBatteryEvent(BaseEvent):
    """Low battery event"""
    event: Literal["low_battery"] = "low_battery"
    device_sn: str
    slack_channel: str
    battery_level: int


class CameraOfflineEvent(BaseEvent):
    """Camera offline event"""
    event: Literal["camera_offline"] = "camera_offline"
    device_sn: str
    slack_channel: str
    reason: str = "health_check_failed"


class SystemErrorEvent(BaseEvent):
    """System error event"""
    event: Literal["system_error"] = "system_error"
    operation: str
    error_type: str
    error_message: str
    retry_count: int
    context: dict
    traceback: Optional[str] = None