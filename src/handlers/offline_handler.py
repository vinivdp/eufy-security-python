"""Camera offline/disconnection handler"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional

from ..models.events import CameraOfflineEvent
from ..services.workato_client import WorkatoWebhook
from ..services.error_logger import ErrorLogger
from ..services.device_health_checker import DeviceHealthChecker

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
        health_checker: DeviceHealthChecker,
        debounce_seconds: int = 30,
    ):
        """
        Initialize offline alarm handler

        Args:
            workato_webhook: WorkatoWebhook instance
            error_logger: ErrorLogger instance
            health_checker: DeviceHealthChecker instance
            debounce_seconds: Wait time before sending offline alert
        """
        self.workato_webhook = workato_webhook
        self.error_logger = error_logger
        self.health_checker = health_checker
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

    async def on_device_state_changed(self, event: dict) -> None:
        """
        Handle device state property change event

        Monitors DeviceState property and triggers health check for problematic states:
        - State 0: Offline (ambiguous - could be sleep or dead)
        - State 1: Online (healthy - ignore)
        - State 2: Manually disabled (user action - ignore)
        - State 3: Offline low battery (check if truly dead)
        - State 4: Remove and readd (device error - check)
        - State 5: Reset and readd (device error - check)

        Args:
            event: Property changed event from WebSocket
                   Format: {"serialNumber": "...", "name": "state", "value": 0}
        """
        device_sn = event.get("serialNumber") or event.get("device_sn")
        property_name = event.get("name")
        state_value = event.get("value")

        # Only handle DeviceState property changes
        if property_name != "state":
            return

        if not device_sn or state_value is None:
            logger.error(f"Device state change event missing required fields: {event}")
            return

        logger.info(f"📊 Device state changed for {device_sn}: {state_value}")

        # Ignore states 1 (Online) and 2 (Manually disabled)
        if state_value in [1, 2]:
            logger.debug(f"Device {device_sn} state {state_value} is not concerning, ignoring")

            # If state is now Online (1), clear any offline tracking
            if state_value == 1:
                if device_sn in self.debounce_tasks:
                    self.debounce_tasks[device_sn].cancel()
                    del self.debounce_tasks[device_sn]
                if device_sn in self.offline_since:
                    del self.offline_since[device_sn]
            return

        # States 0, 3, 4, 5 require health check
        if state_value in [0, 3, 4, 5]:
            state_names = {
                0: "Offline",
                3: "Offline low battery",
                4: "Remove and readd",
                5: "Reset and readd"
            }
            state_name = state_names.get(state_value, "Unknown")

            logger.warning(f"⚠️  Concerning device state for {device_sn}: {state_name} ({state_value})")

            # Run health check to determine if camera is truly unreachable
            await self._check_and_alert(device_sn, state_name)

    async def _check_and_alert(self, device_sn: str, reason: str) -> None:
        """
        Run health check on device and alert if truly unreachable

        Args:
            device_sn: Device serial number
            reason: Reason for check (device state name)
        """
        try:
            # Run health check to verify if camera is responsive
            is_healthy = await self.health_checker.check_device_health(device_sn)

            if is_healthy:
                # Camera is responsive (just sleeping), suppress alert
                logger.info(
                    f"✅ Device {device_sn} passed health check despite state '{reason}' "
                    f"(camera is sleeping/responsive)"
                )

                # Clear any offline tracking
                if device_sn in self.debounce_tasks:
                    self.debounce_tasks[device_sn].cancel()
                    del self.debounce_tasks[device_sn]
                if device_sn in self.offline_since:
                    del self.offline_since[device_sn]

            else:
                # Camera is truly unreachable, send alert
                logger.error(
                    f"❌ Device {device_sn} failed health check with state '{reason}' "
                    f"(camera is dead/unreachable)"
                )

                # Track offline and send alert
                self.offline_since[device_sn] = datetime.now()

                # Send camera offline webhook
                event = CameraOfflineEvent(
                    device_sn=device_sn,
                    reason=reason,
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

        except Exception as e:
            logger.error(f"Error in health check for {device_sn}: {e}", exc_info=True)

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