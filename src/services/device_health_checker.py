"""Device health checker service - polling-based battery and offline monitoring"""

import asyncio
import json
import logging
from typing import Optional
from datetime import datetime, timedelta
from pathlib import Path

from ..models.events import LowBatteryEvent, CameraOfflineEvent
from ..services.camera_registry import CameraRegistry, get_brasilia_now
from ..services.workato_client import WorkatoWebhook
from ..services.error_logger import ErrorLogger

logger = logging.getLogger(__name__)

# Path to persist offline device state
OFFLINE_DEVICES_FILE = Path("/tmp/eufy_offline_devices.json")


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
        # Track offline devices with timestamps (persisted to disk)
        self.offline_devices_timestamps: dict[str, datetime] = self._load_offline_devices()
        # Track last battery alert time per device
        self.last_battery_alert: dict[str, datetime] = {}

        self._running = False
        self._task: Optional[asyncio.Task] = None

    def _load_offline_devices(self) -> dict[str, datetime]:
        """Load offline devices with timestamps from persistent storage"""
        try:
            if OFFLINE_DEVICES_FILE.exists():
                with open(OFFLINE_DEVICES_FILE, "r") as f:
                    data = json.load(f)
                    # Convert ISO timestamps back to datetime objects
                    devices = {}
                    for device_sn, timestamp_str in data.get("offline_devices", {}).items():
                        try:
                            devices[device_sn] = datetime.fromisoformat(timestamp_str)
                        except (ValueError, TypeError):
                            # If timestamp is invalid, use current time
                            devices[device_sn] = get_brasilia_now()
                    logger.info(f"📂 Loaded {len(devices)} offline devices from persistent storage")
                    return devices
        except Exception as e:
            logger.error(f"Failed to load offline devices: {e}")
        return {}

    def _save_offline_devices(self) -> None:
        """Save offline devices with timestamps to persistent storage"""
        try:
            OFFLINE_DEVICES_FILE.parent.mkdir(parents=True, exist_ok=True)
            # Convert datetime objects to ISO format strings
            data = {
                "offline_devices": {
                    device_sn: timestamp.isoformat()
                    for device_sn, timestamp in self.offline_devices_timestamps.items()
                }
            }
            with open(OFFLINE_DEVICES_FILE, "w") as f:
                json.dump(data, f, indent=2)
            logger.debug(f"💾 Saved {len(self.offline_devices_timestamps)} offline devices to persistent storage")
        except Exception as e:
            logger.error(f"Failed to save offline devices: {e}")

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
        # Skip health check if device is offline and within 24-hour cooldown
        if device_sn in self.offline_devices_timestamps:
            last_alert_time = self.offline_devices_timestamps[device_sn]
            now = get_brasilia_now()
            time_since_alert = now - last_alert_time

            if time_since_alert < timedelta(hours=24):
                logger.debug(
                    f"⏸️  Skipping health check for offline device {device_sn} "
                    f"(cooldown: {time_since_alert.total_seconds() / 3600:.1f}h / 24h)"
                )
                return
            else:
                # 24 hours passed, remove from offline set and retry health check
                logger.info(f"🔄 Retrying health check for {device_sn} after 24h cooldown")
                del self.offline_devices_timestamps[device_sn]
                self._save_offline_devices()
                # Reset failure count for fresh start
                self.failure_counts.pop(device_sn, None)

        try:
            # Query device properties (battery level)
            response = await self.websocket_client.send_command(
                "device.get_properties",
                {
                    "serialNumber": device_sn,
                    "properties": ["battery"]
                },
                wait_response=True,
                timeout=10.0
            )

            if response and response.get("success"):
                # Device responded - it's online
                await self._handle_online_response(device_sn, slack_channel, response)
            else:
                # Command failed - log the error code if available
                error_code = response.get("errorCode") if response else "no_response"
                logger.debug(f"Health check failed for {device_sn}: {error_code}")
                await self._handle_failure(device_sn, slack_channel, error_code)

        except asyncio.TimeoutError:
            logger.warning(f"⏱️  Health check timeout for {device_sn}")
            await self._handle_failure(device_sn, slack_channel, "timeout")

        except Exception as e:
            logger.error(f"Health check error for {device_sn}: {e}")
            await self._handle_failure(device_sn, slack_channel, "exception")

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

        # Remove from offline dict (no webhook sent when recovering)
        if device_sn in self.offline_devices_timestamps:
            del self.offline_devices_timestamps[device_sn]
            self._save_offline_devices()
            logger.info(f"📡 Camera {device_sn} recovered from offline state")

        # Check battery level
        # Response structure: {"type": "result", "success": true, "result": {"properties": {"battery": ...}}}
        result = response.get("result", {})
        properties = result.get("properties", {})
        battery_level = properties.get("battery")

        if battery_level is not None:
            logger.debug(f"Battery level for {device_sn}: {battery_level}%")

            if battery_level < self.battery_threshold_percent:
                await self._send_low_battery_alert(device_sn, slack_channel, battery_level)

    async def _handle_failure(self, device_sn: str, slack_channel: str, error_code: str = "unknown") -> None:
        """
        Handle failed health check (increment failure count)

        Args:
            device_sn: Device serial number
            slack_channel: Slack channel for alerts
            error_code: Error code from the failed check
        """
        # Special handling for device_not_found - treat as offline (device is powered off/disconnected)
        # But still require failure threshold to avoid false positives
        if error_code == "device_not_found":
            # Increment failure count
            self.failure_counts[device_sn] = self.failure_counts.get(device_sn, 0) + 1
            failure_count = self.failure_counts[device_sn]

            logger.warning(
                f"📴 Device {device_sn} not found ({failure_count}/{self.failure_threshold} failures)"
            )

            # Only alert after reaching threshold
            if failure_count >= self.failure_threshold:
                if device_sn not in self.offline_devices_timestamps:
                    logger.warning(
                        f"📴 Device {device_sn} is offline (device_not_found - likely powered off)"
                    )
                    await self._send_offline_alert(device_sn, slack_channel)
                    self.offline_devices_timestamps[device_sn] = get_brasilia_now()
                    self._save_offline_devices()
                else:
                    logger.debug(f"Device {device_sn} already marked offline, skipping duplicate alert")
            return

        # Increment failure count
        self.failure_counts[device_sn] = self.failure_counts.get(device_sn, 0) + 1
        failure_count = self.failure_counts[device_sn]

        logger.warning(
            f"❌ Health check failed for {device_sn} ({error_code}) "
            f"({failure_count}/{self.failure_threshold} failures)"
        )

        # Check if threshold reached
        if failure_count >= self.failure_threshold:
            if device_sn not in self.offline_devices_timestamps:
                # First time reaching threshold - send alert
                logger.warning(f"📴 Sending offline alert for {device_sn} (first time at threshold)")
                await self._send_offline_alert(device_sn, slack_channel)
                self.offline_devices_timestamps[device_sn] = get_brasilia_now()
                self._save_offline_devices()
            else:
                logger.debug(f"Device {device_sn} already marked offline, skipping duplicate alert")

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
