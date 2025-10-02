"""Track real-time P2P connection state via WebSocket events"""

import logging
from typing import Dict, Set
from datetime import datetime

logger = logging.getLogger(__name__)


class ConnectionTracker:
    """
    Tracks real-time connection state of stations via WebSocket events.

    This provides accurate, real-time connection status by listening to
    WebSocket connected/disconnected events, unlike the cached API data.
    """

    def __init__(self):
        """Initialize connection tracker"""
        self._connected_stations: Set[str] = set()
        self._connection_times: Dict[str, datetime] = {}
        self._disconnection_times: Dict[str, datetime] = {}
        logger.info("ConnectionTracker initialized")

    def handle_connected(self, serial_number: str) -> None:
        """
        Handle station connected event

        Args:
            serial_number: Station serial number
        """
        if serial_number not in self._connected_stations:
            logger.info(f"📶 Station {serial_number} connected")
            self._connected_stations.add(serial_number)
            self._connection_times[serial_number] = datetime.now()
            if serial_number in self._disconnection_times:
                del self._disconnection_times[serial_number]

    def handle_disconnected(self, serial_number: str) -> None:
        """
        Handle station disconnected event

        Args:
            serial_number: Station serial number
        """
        if serial_number in self._connected_stations:
            logger.info(f"📴 Station {serial_number} disconnected")
            self._connected_stations.remove(serial_number)
            self._disconnection_times[serial_number] = datetime.now()
            if serial_number in self._connection_times:
                del self._connection_times[serial_number]

    def is_connected(self, serial_number: str) -> bool:
        """
        Check if station is currently connected

        Args:
            serial_number: Station serial number

        Returns:
            True if station is connected, False otherwise
        """
        return serial_number in self._connected_stations

    def get_connection_time(self, serial_number: str) -> datetime | None:
        """
        Get when station was connected

        Args:
            serial_number: Station serial number

        Returns:
            Connection timestamp or None if not connected
        """
        return self._connection_times.get(serial_number)

    def get_disconnection_time(self, serial_number: str) -> datetime | None:
        """
        Get when station was disconnected

        Args:
            serial_number: Station serial number

        Returns:
            Disconnection timestamp or None if currently connected
        """
        return self._disconnection_times.get(serial_number)

    def get_all_connected(self) -> Set[str]:
        """
        Get all currently connected stations

        Returns:
            Set of connected station serial numbers
        """
        return self._connected_stations.copy()

    def get_stats(self) -> Dict[str, int]:
        """
        Get connection statistics

        Returns:
            Dictionary with connection stats
        """
        return {
            "connected": len(self._connected_stations),
            "total_tracked": len(self._connection_times) + len(self._disconnection_times),
        }
