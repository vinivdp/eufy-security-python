"""Motion detection handler with state machine logic"""

import logging
from typing import Optional

from ..models.events import MotionDetectedEvent
from ..services.workato_client import WorkatoWebhook
from ..services.error_logger import ErrorLogger
from ..services.camera_registry import CameraRegistry, get_brasilia_now

logger = logging.getLogger(__name__)


class MotionAlarmHandler:
    """
    Handles motion detection events with state machine logic

    State Machine:
    - CLOSED + Motion → OPEN + Send Webhook
    - OPEN + Motion → Send Webhook (no state change)
    - OPEN + 1hr timeout → CLOSED + Send Webhook (handled by StateTimeoutChecker)
    """

    def __init__(
        self,
        camera_registry: CameraRegistry,
        workato_webhook: WorkatoWebhook,
        error_logger: ErrorLogger,
    ):
        """
        Initialize motion alarm handler

        Args:
            camera_registry: CameraRegistry instance
            workato_webhook: WorkatoWebhook instance
            error_logger: ErrorLogger instance
        """
        self.camera_registry = camera_registry
        self.workato_webhook = workato_webhook
        self.error_logger = error_logger

        # Event logging: buffer motion events during open/close cycle
        self.motion_event_logs: dict[str, list[dict]] = {}

    async def on_motion_detected(self, event: dict) -> None:
        """
        Handle motion detected event

        Updates camera state and activity, sends webhook notification.

        Args:
            event: Motion event from WebSocket
                   Format: {"serialNumber": "...", "deviceName": "...", ...}
        """
        device_sn = event.get("serialNumber")

        if not device_sn:
            logger.error(f"Motion event missing serialNumber: {event}")
            return

        # Get camera info from registry
        camera = await self.camera_registry.get_camera(device_sn)
        if not camera:
            logger.warning(f"Motion detected from unknown camera: {device_sn}")
            return

        # Get current state
        old_state = camera.state
        now = get_brasilia_now()

        # Log this event (for all states)
        event_log_entry = {
            "timestamp": now.isoformat(),
            "event_type": event.get("event"),
            "serial_number": device_sn,
        }

        # State machine logic
        if old_state == "closed":
            # CLOSED → OPEN transition
            logger.info(f"🚨 Motion detected: {device_sn} (CLOSED → OPEN)")
            await self.camera_registry.set_state(device_sn, "open")
            new_state = "open"

            # Initialize event log for this open/close cycle
            self.motion_event_logs[device_sn] = [event_log_entry]

            # Send webhook notification
            try:
                webhook_event = MotionDetectedEvent(
                    device_sn=device_sn,
                    slack_channel=camera.slack_channel,
                    state=new_state,
                    latest_activity=now,
                    # Include additional data from WebSocket event
                    device_name=event.get("deviceName"),
                    event_type=event.get("event"),
                    raw_event=event,  # Include full WS event data
                )

                await self.workato_webhook.send_event(webhook_event)
                logger.info(f"✅ Motion webhook sent for {device_sn} to {camera.slack_channel}")

            except Exception as e:
                logger.error(f"Failed to send motion webhook for {device_sn}: {e}")
                await self.error_logger.log_failed_retry(
                    operation="motion_detected_webhook",
                    error=e,
                    context={"device_sn": device_sn, "slack_channel": camera.slack_channel},
                    retry_count=3,
                )

        else:
            # OPEN → OPEN (no state change, no webhook)
            logger.info(
                f"🚨 Motion detected: {device_sn} (OPEN → OPEN, logging event #{len(self.motion_event_logs.get(device_sn, [])) + 1})"
            )
            new_state = "open"

            # Append event to log buffer
            self.motion_event_logs.setdefault(device_sn, []).append(event_log_entry)

        # Update latest activity timestamp
        await self.camera_registry.update_activity(device_sn, now)

    def get_and_clear_event_log(self, device_sn: str) -> list[dict]:
        """
        Get accumulated motion event log and clear buffer

        Args:
            device_sn: Device serial number

        Returns:
            List of motion events logged during the open/close cycle
        """
        return self.motion_event_logs.pop(device_sn, [])

    def get_device_state(self, device_sn: str) -> Optional[dict]:
        """
        Get current state for device

        Args:
            device_sn: Device serial number

        Returns:
            Dict with device state info or None
        """
        camera = self.camera_registry.cameras.get(device_sn)
        if not camera:
            return None

        return {
            "device_sn": camera.device_sn,
            "slack_channel": camera.slack_channel,
            "state": camera.state,
            "latest_activity": camera.latest_activity.isoformat(),
        }
