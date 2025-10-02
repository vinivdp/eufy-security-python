"""Lookup failure handler for offline camera detection"""

import logging
from typing import Optional

from ..models.events import CameraOfflineEvent
from ..services.workato_client import WorkatoWebhook
from ..services.error_logger import ErrorLogger
from ..services.camera_registry import CameraRegistry

logger = logging.getLogger(__name__)


class LookupFailureHandler:
    """
    Handles lookup failure events from standalone cameras

    When a standalone camera (T8B0*, T8150*) fails local network lookup
    and times out, this handler sends an offline notification webhook.
    """

    def __init__(
        self,
        camera_registry: CameraRegistry,
        workato_webhook: WorkatoWebhook,
        error_logger: ErrorLogger,
    ):
        """
        Initialize lookup failure handler

        Args:
            camera_registry: CameraRegistry instance
            workato_webhook: WorkatoWebhook instance
            error_logger: ErrorLogger instance
        """
        self.camera_registry = camera_registry
        self.workato_webhook = workato_webhook
        self.error_logger = error_logger

    async def on_lookup_failure(self, event: dict) -> None:
        """
        Handle lookup failure event

        Sends offline notification webhook when a camera fails to connect
        due to local network lookup failure.

        Args:
            event: Lookup failure event from WebSocket
                   Format: {"serialNumber": "...", "event": "lookup failure"}
        """
        device_sn = event.get("serialNumber")

        if not device_sn:
            logger.error(f"Lookup failure event missing serialNumber: {event}")
            return

        logger.warning(f"📴 Device {device_sn} lookup failure (offline)")

        # Get camera info from registry
        camera = await self.camera_registry.get_camera(device_sn)
        if not camera:
            logger.warning(f"Lookup failure from unknown camera: {device_sn}")
            return

        # Send offline webhook
        offline_event = CameraOfflineEvent(
            device_sn=device_sn,
            slack_channel=camera.slack_channel,
            reason="lookup_failure",
        )

        try:
            await self.workato_webhook.send_event(offline_event)
            logger.info(f"✅ Sent offline webhook for {device_sn}")
        except Exception as e:
            logger.error(f"Failed to send offline webhook for {device_sn}: {e}")
            await self.error_logger.log_failed_retry(
                operation=f"send_offline_webhook_{device_sn}",
                error=e,
                context={"event": event},
                retry_count=1,
            )
