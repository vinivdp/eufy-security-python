"""Battery alarm handler"""

import logging
from datetime import datetime, timedelta
from typing import Dict

from ..models.events import LowBatteryEvent
from ..services.workato_client import WorkatoWebhook
from ..services.error_logger import ErrorLogger

logger = logging.getLogger(__name__)


class BatteryAlarmHandler:
    """
    Handles low battery events

    Uses cooldown to avoid spamming alerts for the same device
    """

    def __init__(
        self,
        workato_webhook: WorkatoWebhook,
        error_logger: ErrorLogger,
        cooldown_hours: int = 24,
    ):
        """
        Initialize battery alarm handler

        Args:
            workato_webhook: WorkatoWebhook instance
            error_logger: ErrorLogger instance
            cooldown_hours: Cooldown period between alerts for same device
        """
        self.workato_webhook = workato_webhook
        self.error_logger = error_logger
        self.cooldown_hours = cooldown_hours

        # Track last alert time per device
        self.last_alert_time: Dict[str, datetime] = {}

    async def on_low_battery(self, event: dict) -> None:
        """
        Handle low battery event

        Args:
            event: Low battery event from WebSocket
        """
        device_sn = event.get("serialNumber") or event.get("device_sn")

        if not device_sn:
            logger.error(f"Low battery event missing device_sn: {event}")
            return

        battery_level = event.get("batteryValue") or event.get("battery_level")

        logger.warning(f"🔋 Low battery detected: {device_sn} ({battery_level}%)")

        # Check cooldown
        if device_sn in self.last_alert_time:
            last_alert = self.last_alert_time[device_sn]
            cooldown_until = last_alert + timedelta(hours=self.cooldown_hours)

            if datetime.now() < cooldown_until:
                remaining = (cooldown_until - datetime.now()).total_seconds() / 3600
                logger.info(
                    f"Low battery alert for {device_sn} is in cooldown "
                    f"({remaining:.1f}h remaining)"
                )
                return

        # Send low battery webhook
        battery_event = LowBatteryEvent(
            device_sn=device_sn,
            battery_level=battery_level,
        )

        try:
            await self.workato_webhook.send_event(battery_event)
            logger.info(f"✅ Low battery webhook sent for {device_sn}")

            # Update last alert time
            self.last_alert_time[device_sn] = datetime.now()

        except Exception as e:
            logger.error(f"Failed to send low battery webhook: {e}")
            await self.error_logger.log_failed_retry(
                operation="low_battery_webhook",
                error=e,
                context={"device_sn": device_sn, "battery_level": battery_level},
                retry_count=3,
            )

    def get_battery_alerts(self) -> list[dict]:
        """Get list of devices that sent battery alerts"""
        alerts = []

        for device_sn, alert_time in self.last_alert_time.items():
            hours_since = (datetime.now() - alert_time).total_seconds() / 3600
            cooldown_remaining = max(0, self.cooldown_hours - hours_since)

            alerts.append({
                "device_sn": device_sn,
                "last_alert_time": alert_time.isoformat(),
                "hours_since_alert": round(hours_since, 1),
                "cooldown_remaining_hours": round(cooldown_remaining, 1),
            })

        return alerts