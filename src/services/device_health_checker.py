"""Device health checker service - polling-based battery and offline monitoring"""

import asyncio
import logging
from typing import Optional
from datetime import datetime, timedelta

from ..models.events import LowBatteryEvent, CameraOfflineEvent
from ..services.camera_registry import CameraRegistry, get_brasilia_now
from ..services.workato_client import WorkatoWebhook
from ..services.error_logger import ErrorLogger

logger = logging.getLogger(__name__)


class DeviceHealthChecker:
    """
    Polling-based health monitoring service

    Periodically checks all registered cameras for:
    - Battery level (send alert if < threshold)
    - Online status (send alert after N failures)
    """

    def __init__(
        self,
        websocket_client: "WebSocketClient",
        camera_registry: CameraRegistry,
        workato_webhook: WorkatoWebhook,
        error_logger: ErrorLogger,
        polling_interval_minutes: int = 5,
        failure_threshold: int = 3,
        battery_threshold_percent: int = 30,
        battery_cooldown_hours: int = 24,
    ):
        """
        Initialize device health checker

        Args:
            websocket_client: WebSocketClient for sending commands
            camera_registry: CameraRegistry instance
            workato_webhook: WorkatoWebhook instance
            error_logger: ErrorLogger instance
            polling_interval_minutes: Minutes between health checks
            failure_threshold: Number of failures before marking offline
            battery_threshold_percent: Battery % threshold for alert
            battery_cooldown_hours: Hours between battery alerts per camera
        """
        self.websocket_client = websocket_client
        self.camera_registry = camera_registry
        self.workato_webhook = workato_webhook
        self.error_logger = error_logger
        self.polling_interval_minutes = polling_interval_minutes
        self.failure_threshold = failure_threshold
        self.battery_threshold_percent = battery_threshold_percent
        self.battery_cooldown_hours = battery_cooldown_hours

        # Track consecutive failures per device
        self.failure_counts: dict[str, int] = {}
        # Track offline devices to avoid duplicate alerts
        self.offline_devices: set[str] = set()
        # Track last battery alert time per device
        self.last_battery_alert: dict[str, datetime] = {}

        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the background health check polling loop"""
        if self._running:
            logger.warning("DeviceHealthChecker already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            f"✅ DeviceHealthChecker started "
            f"(interval: {self.polling_interval_minutes}m, "
            f"battery threshold: {self.battery_threshold_percent}%, "
            f"failure threshold: {self.failure_threshold})"
        )

    async def stop(self) -> None:
        """Stop the background health check loop"""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("DeviceHealthChecker stopped")

    async def _run_loop(self) -> None:
        """Background loop that periodically checks all cameras"""
        logger.info("DeviceHealthChecker loop started")

        while self._running:
            try:
                await self._check_all_cameras()
                await asyncio.sleep(self.polling_interval_minutes * 60)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in DeviceHealthChecker loop: {e}", exc_info=True)
                await asyncio.sleep(60)  # Wait 1 minute before retry

    async def _check_all_cameras(self) -> None:
        """Check battery and online status for all registered cameras"""
        cameras = await self.camera_registry.get_all_cameras()

        logger.info(f"🏥 Running health check on {len(cameras)} cameras...")

        for camera in cameras:
            await self._check_camera_health(camera.device_sn, camera.slack_channel)
            await asyncio.sleep(1)  # Small delay between cameras

    async def _check_camera_health(self, device_sn: str, slack_channel: str) -> None:
        """
        Check health of a single camera (battery + online status)

        Args:
            device_sn: Device serial number
            slack_channel: Slack channel for alerts
        """
        try:
            # Query device properties (battery level)
            response = await asyncio.wait_for(
                self.websocket_client.send_command(
                    "device.get_properties",
                    {
                        "serialNumber": device_sn,
                        "properties": ["battery"]
                    }
                ),
                timeout=10.0
            )

            if response and response.get("success"):
                # Device responded - it's online
                await self._handle_online_response(device_sn, slack_channel, response)
            else:
                # Command failed
                await self._handle_failure(device_sn, slack_channel)

        except asyncio.TimeoutError:
            logger.warning(f"⏱️  Health check timeout for {device_sn}")
            await self._handle_failure(device_sn, slack_channel)

        except Exception as e:
            logger.error(f"Health check error for {device_sn}: {e}")
            await self._handle_failure(device_sn, slack_channel)

    async def _handle_online_response(self, device_sn: str, slack_channel: str, response: dict) -> None:
        """
        Handle successful health check response

        Args:
            device_sn: Device serial number
            slack_channel: Slack channel for alerts
            response: Response from get_properties command
        """
        # Device is online - reset failure count
        if device_sn in self.failure_counts:
            logger.info(f"✅ Camera {device_sn} is back online")
            del self.failure_counts[device_sn]

        # Remove from offline set (no webhook sent when recovering)
        if device_sn in self.offline_devices:
            self.offline_devices.remove(device_sn)
            logger.info(f"📡 Camera {device_sn} recovered from offline state")

        # Check battery level
        battery_level = response.get("battery")
        if battery_level is not None:
            logger.debug(f"Battery level for {device_sn}: {battery_level}%")

            if battery_level < self.battery_threshold_percent:
                await self._send_low_battery_alert(device_sn, slack_channel, battery_level)

    async def _handle_failure(self, device_sn: str, slack_channel: str) -> None:
        """
        Handle failed health check (increment failure count)

        Args:
            device_sn: Device serial number
            slack_channel: Slack channel for alerts
        """
        # Increment failure count
        self.failure_counts[device_sn] = self.failure_counts.get(device_sn, 0) + 1
        failure_count = self.failure_counts[device_sn]

        logger.warning(
            f"❌ Health check failed for {device_sn} "
            f"({failure_count}/{self.failure_threshold} failures)"
        )

        # Check if threshold reached
        if failure_count >= self.failure_threshold:
            if device_sn not in self.offline_devices:
                # First time reaching threshold - send alert
                await self._send_offline_alert(device_sn, slack_channel)
                self.offline_devices.add(device_sn)

    async def _send_low_battery_alert(self, device_sn: str, slack_channel: str, battery_level: int) -> None:
        """
        Send low battery webhook

        Args:
            device_sn: Device serial number
            slack_channel: Slack channel for alert
            battery_level: Current battery percentage
        """
        # Check cooldown
        now = get_brasilia_now()
        last_alert = self.last_battery_alert.get(device_sn)

        if last_alert:
            time_since_alert = now - last_alert
            if time_since_alert < timedelta(hours=self.battery_cooldown_hours):
                logger.debug(
                    f"Battery alert for {device_sn} skipped (cooldown: "
                    f"{time_since_alert.total_seconds() / 3600:.1f}h / {self.battery_cooldown_hours}h)"
                )
                return

        # Send alert
        try:
            event = LowBatteryEvent(
                device_sn=device_sn,
                slack_channel=slack_channel,
                battery_level=battery_level,
            )

            await self.workato_webhook.send_event(event)
            self.last_battery_alert[device_sn] = now
            logger.warning(f"🔋 Low battery alert sent for {device_sn}: {battery_level}%")

        except Exception as e:
            logger.error(f"Failed to send low battery alert for {device_sn}: {e}")
            await self.error_logger.log_failed_retry(
                operation="low_battery_webhook",
                error=e,
                context={"device_sn": device_sn, "battery_level": battery_level},
                retry_count=3,
            )

    async def _send_offline_alert(self, device_sn: str, slack_channel: str) -> None:
        """
        Send offline webhook

        Args:
            device_sn: Device serial number
            slack_channel: Slack channel for alert
        """
        try:
            event = CameraOfflineEvent(
                device_sn=device_sn,
                slack_channel=slack_channel,
                reason="health_check_failed",
            )

            await self.workato_webhook.send_event(event)
            logger.error(f"📴 Offline alert sent for {device_sn} (failed {self.failure_threshold} checks)")

        except Exception as e:
            logger.error(f"Failed to send offline alert for {device_sn}: {e}")
            await self.error_logger.log_failed_retry(
                operation="camera_offline_webhook",
                error=e,
                context={"device_sn": device_sn, "reason": "health_check_failed"},
                retry_count=3,
            )
