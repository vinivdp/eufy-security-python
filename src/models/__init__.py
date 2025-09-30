"""Data models"""

from .events import (
    BaseEvent,
    MotionDetectedEvent,
    MotionStoppedEvent,
    LowBatteryEvent,
    CameraOfflineEvent,
    SystemErrorEvent,
)
from .errors import ErrorLog

__all__ = [
    "BaseEvent",
    "MotionDetectedEvent",
    "MotionStoppedEvent",
    "LowBatteryEvent",
    "CameraOfflineEvent",
    "SystemErrorEvent",
    "ErrorLog",
]