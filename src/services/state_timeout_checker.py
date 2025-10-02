"""State timeout checker service - auto-closes cameras after inactivity"""

import asyncio
import logging
from datetime import timedelta
from typing import Optional

from ..models.events import MotionStoppedEvent
from ..services.camera_registry import CameraRegistry, get_brasilia_now
from ..services.workato_client import WorkatoWebhook
from ..services.error_logger import ErrorLogger

logger = logging.getLogger(__name__)


class StateTimeoutChecker:
    """
    Background service that checks for cameras in 'open' state with old activity

    If a camera is 'open' and latest_activity is older than timeout threshold,
    transitions it to 'closed' and sends a motion_stopped webhook.
    """

    def __init__(
        self,
        camera_registry: CameraRegistry,
        workato_webhook: WorkatoWebhook,
        error_logger: ErrorLogger,
        motion_handler: "MotionAlarmHandler",
        timeout_minutes: int = 60,
        check_interval_seconds: int = 60,
    ):
        """
        Initialize state timeout checker

        Args:
            camera_registry: CameraRegistry instance
            workato_webhook: WorkatoWebhook instance
            error_logger: ErrorLogger instance
            motion_handler: MotionAlarmHandler instance (for event logs)
            timeout_minutes: Minutes of inactivity before auto-closing (default 60)
            check_interval_seconds: How often to check for timeouts (default 60s)
        """
        self.camera_registry = camera_registry
        self.workato_webhook = workato_webhook
        self.error_logger = error_logger
        self.motion_handler = motion_handler
        self.timeout_minutes = timeout_minutes
        self.check_interval_seconds = check_interval_seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the background timeout checker loop"""
        if self._running:
            logger.warning("StateTimeoutChecker already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"✅ StateTimeoutChecker started (timeout: {self.timeout_minutes}m, check interval: {self.check_interval_seconds}s)")

    async def stop(self) -> None:
        """Stop the background timeout checker loop"""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("StateTimeoutChecker stopped")

    async def _run_loop(self) -> None:
        """Background loop that periodically checks for timeouts"""
        logger.info("StateTimeoutChecker loop started")

        while self._running:
            try:
                await self._check_timeouts()
                await asyncio.sleep(self.check_interval_seconds)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in StateTimeoutChecker loop: {e}", exc_info=True)
                await asyncio.sleep(self.check_interval_seconds)

    async def _check_timeouts(self) -> None:
        """Check all cameras for timeout condition"""
        now = get_brasilia_now()
        timeout_threshold = timedelta(minutes=self.timeout_minutes)

        # Get all cameras in 'open' state
        open_cameras = await self.camera_registry.get_cameras_by_state("open")

        for camera in open_cameras:
            # Calculate time since last activity
            time_since_activity = now - camera.latest_activity

            if time_since_activity >= timeout_threshold:
                # Timeout reached - transition to closed
                logger.info(
                    f"⏰ Timeout reached for {camera.device_sn}: "
                    f"{time_since_activity.total_seconds() / 60:.1f}m since last activity"
                )

                await self._transition_to_closed(camera.device_sn, int(time_since_activity.total_seconds()))

    async def _transition_to_closed(self, device_sn: str, duration_seconds: int) -> None:
        """
        Transition camera from open to closed and send webhook

        Args:
            device_sn: Device serial number
            duration_seconds: Duration camera was open
        """
        try:
            # Get camera info (need slack_channel)
            camera = await self.camera_registry.get_camera(device_sn)
            if not camera:
                logger.error(f"Camera not found in registry: {device_sn}")
                return

            # Update state to closed
            await self.camera_registry.set_state(device_sn, "closed")

            logger.info(f"📴 Camera {device_sn} auto-closed after {duration_seconds / 60:.1f}m (OPEN → CLOSED)")

            # Get accumulated event log from motion handler
            event_log = self.motion_handler.get_and_clear_event_log(device_sn)

            # Send motion_stopped webhook with event log
            event = MotionStoppedEvent(
                device_sn=device_sn,
                slack_channel=camera.slack_channel,
                state="closed",
                duration_seconds=duration_seconds,
                latest_activity=camera.latest_activity,
                event_log=event_log,  # Include accumulated motion events
            )

            await self.workato_webhook.send_event(event)
            logger.info(
                f"✅ Motion stopped webhook sent for {device_sn} (timeout) with {len(event_log)} logged events"
            )

        except Exception as e:
            logger.error(f"Error transitioning {device_sn} to closed: {e}")
            await self.error_logger.log_failed_retry(
                operation="state_timeout_close",
                error=e,
                context={"device_sn": device_sn, "duration_seconds": duration_seconds},
                retry_count=3,
            )
