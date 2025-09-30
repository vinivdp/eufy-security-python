"""Camera offline/disconnection handler"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional

from ..models.events import CameraOfflineEvent
from ..services.workato_client import WorkatoWebhook
from ..services.error_logger import ErrorLogger

logger = logging.getLogger(__name__)


class OfflineAlarmHandler:
    """
    Handles camera offline/disconnection events

    Uses debounce logic to avoid false alarms from temporary disconnections
    """

    def __init__(
        self,
        workato_webhook: WorkatoWebhook,
        error_logger: ErrorLogger,
        debounce_seconds: int = 30,
    ):
        """
        Initialize offline alarm handler

        Args:
            workato_webhook: WorkatoWebhook instance
            error_logger: ErrorLogger instance
            debounce_seconds: Wait time before sending offline alert
        """
        self.workato_webhook = workato_webhook
        self.error_logger = error_logger
        self.debounce_seconds = debounce_seconds

        # Track debounce tasks per device
        self.debounce_tasks: Dict[str, asyncio.Task] = {}
        self.offline_since: Dict[str, datetime] = {}

    async def on_disconnect(self, event: dict) -> None:
        """
        Handle device disconnect event

        Args:
            event: Disconnect event from WebSocket
        """
        device_sn = event.get("serialNumber") or event.get("device_sn")

        if not device_sn:
            logger.error(f"Disconnect event missing device_sn: {event}")
            return

        logger.warning(f"⚠️  Camera disconnect detected: {device_sn}")

        # Cancel existing debounce task if any
        if device_sn in self.debounce_tasks:
            self.debounce_tasks[device_sn].cancel()

        # Start new debounce task
        self.offline_since[device_sn] = datetime.now()
        self.debounce_tasks[device_sn] = asyncio.create_task(
            self._debounce_and_alert(device_sn, event.get("event"))
        )

    async def on_reconnect(self, event: dict) -> None:
        """
        Handle device reconnect event

        Args:
            event: Reconnect event from WebSocket
        """
        device_sn = event.get("serialNumber") or event.get("device_sn")

        if not device_sn:
            return

        # Cancel debounce task if exists (camera came back online)
        if device_sn in self.debounce_tasks:
            self.debounce_tasks[device_sn].cancel()
            del self.debounce_tasks[device_sn]

        if device_sn in self.offline_since:
            offline_duration = (datetime.now() - self.offline_since[device_sn]).total_seconds()
            logger.info(
                f"✅ Camera reconnected: {device_sn} "
                f"(was offline for {offline_duration:.0f}s)"
            )
            del self.offline_since[device_sn]
        else:
            logger.info(f"✅ Camera connected: {device_sn}")

    async def _debounce_and_alert(self, device_sn: str, reason: Optional[str]) -> None:
        """Wait for debounce period, then send offline alert"""
        try:
            await asyncio.sleep(self.debounce_seconds)

            # Still offline after debounce period
            logger.error(
                f"❌ Camera offline for {self.debounce_seconds}s: {device_sn}"
            )

            # Send camera offline webhook
            event = CameraOfflineEvent(
                device_sn=device_sn,
                reason=reason or "disconnected",
            )

            try:
                await self.workato_webhook.send_event(event)
                logger.info(f"✅ Camera offline webhook sent for {device_sn}")

            except Exception as e:
                logger.error(f"Failed to send camera offline webhook: {e}")
                await self.error_logger.log_failed_retry(
                    operation="camera_offline_webhook",
                    error=e,
                    context={"device_sn": device_sn, "reason": reason},
                    retry_count=3,
                )

        except asyncio.CancelledError:
            # Camera came back online before debounce period
            logger.info(f"Camera {device_sn} reconnected before alert")

    def get_offline_devices(self) -> list[dict]:
        """Get list of currently offline devices"""
        offline_devices = []

        for device_sn, offline_time in self.offline_since.items():
            offline_duration = (datetime.now() - offline_time).total_seconds()
            offline_devices.append({
                "device_sn": device_sn,
                "offline_since": offline_time.isoformat(),
                "offline_duration_seconds": int(offline_duration),
            })

        return offline_devices