"""Motion alarm handler"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

from ..models.events import MotionDetectedEvent, MotionStoppedEvent
from ..services.video_recorder import VideoRecorder
from ..services.workato_client import WorkatoWebhook
from ..services.error_logger import ErrorLogger
from ..clients.websocket_client import WebSocketClient

logger = logging.getLogger(__name__)


class MotionState:
    """State tracking for motion detection"""

    def __init__(self, device_sn: str):
        self.device_sn = device_sn
        self.first_motion_time: Optional[datetime] = None
        self.last_motion_time: Optional[datetime] = None
        self.is_recording = False
        self.snooze_until: Optional[datetime] = None
        self.video_url: Optional[str] = None
        self.no_motion_task: Optional[asyncio.Task] = None
        self.max_duration_task: Optional[asyncio.Task] = None


class MotionAlarmHandler:
    """
    Handles motion detection events and video recording lifecycle

    Workflow:
    1. Motion detected -> Start recording -> Send webhook
    2. No motion for 60s -> Stop recording -> Send webhook
    3. Max 15min -> Stop recording -> Snooze for 1 hour
    """

    def __init__(
        self,
        video_recorder: VideoRecorder,
        workato_webhook: WorkatoWebhook,
        error_logger: ErrorLogger,
        websocket_client: WebSocketClient,
        motion_timeout_seconds: int = 60,
        max_duration_seconds: int = 900,
        snooze_duration_seconds: int = 3600,
    ):
        """
        Initialize motion alarm handler

        Args:
            video_recorder: VideoRecorder instance
            workato_webhook: WorkatoWebhook instance
            error_logger: ErrorLogger instance
            websocket_client: WebSocketClient instance
            motion_timeout_seconds: Seconds of no motion before stopping
            max_duration_seconds: Maximum recording duration
            snooze_duration_seconds: Snooze duration after max reached
        """
        self.video_recorder = video_recorder
        self.workato_webhook = workato_webhook
        self.error_logger = error_logger
        self.websocket_client = websocket_client
        self.motion_timeout = motion_timeout_seconds
        self.max_duration = max_duration_seconds
        self.snooze_duration = snooze_duration_seconds

        # Track state per device
        self.device_states: Dict[str, MotionState] = {}

    async def on_motion_detected(self, event: dict) -> None:
        """
        Handle motion detected event

        Args:
            event: Motion detected event from WebSocket
        """
        device_sn = event.get("serialNumber") or event.get("device_sn")

        if not device_sn:
            logger.error(f"Motion event missing device_sn: {event}")
            return

        logger.info(f"🚨 Motion detected: {device_sn}")

        # Get or create device state
        if device_sn not in self.device_states:
            self.device_states[device_sn] = MotionState(device_sn)

        state = self.device_states[device_sn]

        # Check if snoozed
        if state.snooze_until and datetime.now() < state.snooze_until:
            remaining = (state.snooze_until - datetime.now()).total_seconds()
            logger.info(f"Device {device_sn} is snoozed for {remaining:.0f}s more")
            return

        # Update motion times
        now = datetime.now()
        state.last_motion_time = now

        if not state.is_recording:
            # Start new recording
            state.first_motion_time = now
            await self._start_recording(state)
        else:
            # Reset no-motion timer
            if state.no_motion_task:
                state.no_motion_task.cancel()
            state.no_motion_task = asyncio.create_task(
                self._wait_for_no_motion(state)
            )

    async def _start_recording(self, state: MotionState) -> None:
        """Start recording for device"""
        try:
            # Start video recording
            video_url = await self.video_recorder.start_recording(state.device_sn)
            state.video_url = video_url
            state.is_recording = True

            logger.info(f"📹 Recording started for {state.device_sn}: {video_url}")

            # Send motion detected webhook
            event = MotionDetectedEvent(
                device_sn=state.device_sn,
                video_url=video_url,
            )

            await self.workato_webhook.send_event(event)
            logger.info(f"✅ Motion detected webhook sent for {state.device_sn}")

            # Start timers
            state.no_motion_task = asyncio.create_task(
                self._wait_for_no_motion(state)
            )
            state.max_duration_task = asyncio.create_task(
                self._wait_for_max_duration(state)
            )

        except Exception as e:
            logger.error(f"Error starting recording for {state.device_sn}: {e}")
            await self.error_logger.log_failed_retry(
                operation="start_recording",
                error=e,
                context={"device_sn": state.device_sn},
                retry_count=3,
            )

    async def _wait_for_no_motion(self, state: MotionState) -> None:
        """Wait for motion timeout, then stop recording"""
        try:
            await asyncio.sleep(self.motion_timeout)

            logger.info(
                f"No motion for {self.motion_timeout}s on {state.device_sn}, stopping recording"
            )
            await self._stop_recording(state, reason="no_motion")

        except asyncio.CancelledError:
            # Timer was reset due to new motion
            pass

    async def _wait_for_max_duration(self, state: MotionState) -> None:
        """Wait for max duration, then stop and snooze"""
        try:
            await asyncio.sleep(self.max_duration)

            logger.warning(
                f"Max recording duration ({self.max_duration}s) reached for {state.device_sn}"
            )
            await self._stop_recording(state, reason="max_duration")

            # Snooze the device
            state.snooze_until = datetime.now() + timedelta(seconds=self.snooze_duration)
            logger.info(f"Device {state.device_sn} snoozed for {self.snooze_duration}s")

            # Send snooze command to device
            try:
                await self.websocket_client.send_command(
                    "device.snooze",
                    {"serialNumber": state.device_sn, "value": True}
                )
            except Exception as e:
                logger.error(f"Failed to send snooze command: {e}")

        except asyncio.CancelledError:
            # Recording stopped before max duration
            pass

    async def _stop_recording(self, state: MotionState, reason: str = "unknown") -> None:
        """Stop recording for device"""
        if not state.is_recording:
            return

        try:
            # Cancel timers
            if state.no_motion_task:
                state.no_motion_task.cancel()
            if state.max_duration_task:
                state.max_duration_task.cancel()

            # Stop video recording
            result = await self.video_recorder.stop_recording(state.device_sn)

            if not result:
                logger.warning(f"No active recording to stop for {state.device_sn}")
                return

            video_url, duration_seconds = result
            state.is_recording = False

            logger.info(
                f"⏹️  Recording stopped for {state.device_sn} "
                f"(duration: {duration_seconds}s, reason: {reason})"
            )

            # Send motion stopped webhook
            event = MotionStoppedEvent(
                device_sn=state.device_sn,
                video_url=video_url,
                duration_seconds=duration_seconds,
            )

            await self.workato_webhook.send_event(event)
            logger.info(f"✅ Motion stopped webhook sent for {state.device_sn}")

        except Exception as e:
            logger.error(f"Error stopping recording for {state.device_sn}: {e}")
            await self.error_logger.log_failed_retry(
                operation="stop_recording",
                error=e,
                context={"device_sn": state.device_sn, "reason": reason},
                retry_count=3,
            )

    def get_device_state(self, device_sn: str) -> Optional[dict]:
        """Get current state for device"""
        if device_sn not in self.device_states:
            return None

        state = self.device_states[device_sn]

        return {
            "device_sn": device_sn,
            "is_recording": state.is_recording,
            "video_url": state.video_url,
            "first_motion_time": state.first_motion_time.isoformat() if state.first_motion_time else None,
            "last_motion_time": state.last_motion_time.isoformat() if state.last_motion_time else None,
            "snooze_until": state.snooze_until.isoformat() if state.snooze_until else None,
        }