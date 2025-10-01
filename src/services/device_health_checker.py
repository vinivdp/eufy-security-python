"""Device health checker service"""

import asyncio
import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class DeviceHealthChecker:
    """
    Service to verify camera availability via simple health check commands

    This class can be used to distinguish between sleeping cameras (responsive)
    and truly offline/dead cameras (unresponsive).
    """

    def __init__(
        self,
        websocket_client: "WebSocketClient",
        health_check_timeout: int = 10,
    ):
        """
        Initialize device health checker

        Args:
            websocket_client: WebSocketClient instance for sending commands
            health_check_timeout: Timeout in seconds for health check commands
        """
        self.websocket_client = websocket_client
        self.health_check_timeout = health_check_timeout

        # Track last health check results: device_sn -> (is_healthy, timestamp)
        self.last_check_results: dict[str, tuple[bool, datetime]] = {}

    async def check_device_health(self, device_sn: str) -> bool:
        """
        Check if device is responsive by sending a lightweight query

        Uses device.get_properties command to query static metadata (model).
        If the device responds, it's reachable (even if sleeping).
        If it times out or errors, it's truly offline/dead.

        Args:
            device_sn: Device serial number

        Returns:
            True if device is responsive, False if unreachable
        """
        logger.info(f"🏥 Running health check on device: {device_sn}")

        try:
            # Send lightweight get_properties command for static metadata
            response = await asyncio.wait_for(
                self._send_health_check_command(device_sn),
                timeout=self.health_check_timeout,
            )

            # If we got any response, device is reachable
            is_healthy = response is not None
            self.last_check_results[device_sn] = (is_healthy, datetime.now())

            if is_healthy:
                logger.info(f"✅ Health check passed for {device_sn} (device responsive)")
            else:
                logger.warning(f"❌ Health check failed for {device_sn} (no response)")

            return is_healthy

        except asyncio.TimeoutError:
            logger.error(f"❌ Health check timeout for {device_sn} (device unreachable)")
            self.last_check_results[device_sn] = (False, datetime.now())
            return False

        except Exception as e:
            logger.error(f"❌ Health check error for {device_sn}: {e}")
            self.last_check_results[device_sn] = (False, datetime.now())
            return False

    async def _send_health_check_command(self, device_sn: str) -> Optional[dict]:
        """
        Send the actual health check command to the device

        Currently uses device.get_properties to query the model property.
        This is a lightweight read-only operation that doesn't drain battery.

        Args:
            device_sn: Device serial number

        Returns:
            Response dict if successful, None if failed
        """
        try:
            # Query device model (static metadata, lightweight)
            response = await self.websocket_client.send_command(
                "device.get_properties",
                {
                    "serialNumber": device_sn,
                    "properties": ["model"]
                }
            )

            return response

        except Exception as e:
            logger.debug(f"Health check command failed for {device_sn}: {e}")
            return None

    def get_last_check_result(self, device_sn: str) -> Optional[tuple[bool, datetime]]:
        """
        Get the last health check result for a device

        Args:
            device_sn: Device serial number

        Returns:
            Tuple of (is_healthy, timestamp) or None if never checked
        """
        return self.last_check_results.get(device_sn)

    async def run_scheduled_health_checks(self, device_sns: list[str], interval_hours: int = 24) -> None:
        """
        Run periodic health checks on a list of devices

        This can be used for daily health monitoring of all known cameras.

        Args:
            device_sns: List of device serial numbers to check
            interval_hours: Hours between health checks
        """
        logger.info(f"Starting scheduled health checks for {len(device_sns)} devices (every {interval_hours}h)")

        while True:
            try:
                for device_sn in device_sns:
                    await self.check_device_health(device_sn)
                    await asyncio.sleep(1)  # Small delay between checks

                # Wait until next scheduled check
                await asyncio.sleep(interval_hours * 3600)

            except Exception as e:
                logger.error(f"Error in scheduled health checks: {e}", exc_info=True)
                await asyncio.sleep(300)  # Wait 5 minutes before retry
