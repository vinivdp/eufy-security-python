"""Event handler modules"""

from .motion_handler import MotionAlarmHandler

# Note: OfflineAlarmHandler and BatteryAlarmHandler are deprecated
# Offline and battery monitoring now handled by DeviceHealthChecker (polling-based)

__all__ = ["MotionAlarmHandler"]