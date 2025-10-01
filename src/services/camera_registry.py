"""Camera registry service for managing camera state and metadata"""

import csv
import logging
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

BRASILIA_TZ = ZoneInfo("America/Sao_Paulo")


def get_brasilia_now() -> datetime:
    """Get current datetime in Brasília timezone"""
    return datetime.now(BRASILIA_TZ)


@dataclass
class CameraInfo:
    """Camera information from registry"""
    device_sn: str
    slack_channel: str
    latest_activity: datetime
    state: str  # "open" or "closed"


class CameraRegistry:
    """
    Manages camera registry loaded from CSV file

    Tracks camera state (open/closed), latest activity, and Slack channel mapping.
    Persists changes back to CSV file on every update.
    """

    def __init__(self, registry_path: str = "config/cameras.txt"):
        """
        Initialize camera registry

        Args:
            registry_path: Path to cameras.txt CSV file
        """
        self.registry_path = Path(registry_path)
        self.cameras: dict[str, CameraInfo] = {}
        self._lock = asyncio.Lock()

    async def load(self) -> None:
        """Load camera registry from CSV file"""
        async with self._lock:
            if not self.registry_path.exists():
                logger.warning(f"Camera registry file not found: {self.registry_path}")
                return

            try:
                with open(self.registry_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        device_sn = row['Camera_SN'].strip()
                        slack_channel = row['Slack_channel'].strip()
                        latest_activity_str = row['latest_activity'].strip()
                        state = row['state'].strip()

                        # Parse datetime with timezone
                        latest_activity = datetime.fromisoformat(latest_activity_str)

                        self.cameras[device_sn] = CameraInfo(
                            device_sn=device_sn,
                            slack_channel=slack_channel,
                            latest_activity=latest_activity,
                            state=state
                        )

                logger.info(f"✅ Loaded {len(self.cameras)} cameras from registry")

            except Exception as e:
                logger.error(f"Failed to load camera registry: {e}", exc_info=True)
                raise

    async def save(self) -> None:
        """Save camera registry to CSV file"""
        async with self._lock:
            try:
                with open(self.registry_path, 'w', encoding='utf-8', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(['Camera_SN', 'Slack_channel', 'latest_activity', 'state'])

                    for camera in self.cameras.values():
                        writer.writerow([
                            camera.device_sn,
                            camera.slack_channel,
                            camera.latest_activity.isoformat(),
                            camera.state
                        ])

                logger.debug(f"Saved camera registry ({len(self.cameras)} cameras)")

            except Exception as e:
                logger.error(f"Failed to save camera registry: {e}", exc_info=True)

    async def get_camera(self, device_sn: str) -> Optional[CameraInfo]:
        """Get camera info by serial number"""
        async with self._lock:
            return self.cameras.get(device_sn)

    async def update_activity(self, device_sn: str, activity_time: Optional[datetime] = None) -> None:
        """
        Update latest activity time for a camera

        Args:
            device_sn: Device serial number
            activity_time: Activity timestamp (defaults to now in Brasília time)
        """
        async with self._lock:
            if device_sn not in self.cameras:
                logger.warning(f"Camera not in registry: {device_sn}")
                return

            if activity_time is None:
                activity_time = get_brasilia_now()

            self.cameras[device_sn].latest_activity = activity_time

        # Save after updating
        await self.save()

    async def set_state(self, device_sn: str, state: str) -> None:
        """
        Set camera state (open/closed)

        Args:
            device_sn: Device serial number
            state: New state ("open" or "closed")
        """
        if state not in ["open", "closed"]:
            raise ValueError(f"Invalid state: {state}. Must be 'open' or 'closed'")

        async with self._lock:
            if device_sn not in self.cameras:
                logger.warning(f"Camera not in registry: {device_sn}")
                return

            old_state = self.cameras[device_sn].state
            self.cameras[device_sn].state = state

            if old_state != state:
                logger.info(f"Camera {device_sn} state: {old_state} → {state}")

        # Save after updating
        await self.save()

    async def get_all_cameras(self) -> list[CameraInfo]:
        """Get list of all cameras"""
        async with self._lock:
            return list(self.cameras.values())

    async def get_cameras_by_state(self, state: str) -> list[CameraInfo]:
        """Get cameras filtered by state"""
        async with self._lock:
            return [cam for cam in self.cameras.values() if cam.state == state]

    def get_slack_channel(self, device_sn: str) -> Optional[str]:
        """Get Slack channel for a camera (synchronous)"""
        camera = self.cameras.get(device_sn)
        return camera.slack_channel if camera else None
