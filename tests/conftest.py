"""Pytest configuration and shared fixtures"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock
import pytest

from src.utils.config import (
    AppConfig,
    ServerConfig,
    EufyConfig,
    RecordingConfig,
    WorkatoConfig,
    ErrorLoggingConfig,
    MotionConfig,
    AlertsConfig,
    BatteryAlertConfig,
    OfflineAlertConfig,
    LoggingConfig,
)
from src.services.camera_registry import CameraRegistry, CameraInfo, get_brasilia_now


@pytest.fixture
def mock_config() -> AppConfig:
    """Create a mock AppConfig for testing"""
    return AppConfig(
        server=ServerConfig(
            host="0.0.0.0",
            port=10000,
            public_url="http://test.example.com"
        ),
        eufy=EufyConfig(
            websocket_url="ws://test:3000/ws",
            reconnect_delay=1.0,
            heartbeat_interval=10.0
        ),
        recording=RecordingConfig(
            storage_path="./test_recordings",
            retention_days=7
        ),
        workato=WorkatoConfig(
            webhook_url="https://test.workato.com/webhook",
            timeout_seconds=10,
            rate_limit_per_second=10
        ),
        error_logging=ErrorLoggingConfig(
            send_to_workato=False,
            keep_in_memory=10
        ),
        motion=MotionConfig(
            state_timeout_minutes=60
        ),
        alerts=AlertsConfig(
            battery=BatteryAlertConfig(cooldown_hours=1),
            offline=OfflineAlertConfig(
                polling_interval_minutes=5,
                failure_threshold=3,
                battery_threshold_percent=30
            )
        ),
        logging=LoggingConfig(
            level="INFO",
            format="%(message)s",
            file="./test.log",
            max_size_mb=10,
            backup_count=1
        )
    )


@pytest.fixture
def mock_websocket_client():
    """Create a mock WebSocketClient"""
    client = AsyncMock()
    client.send_command = AsyncMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.is_connected = MagicMock(return_value=True)
    return client


@pytest.fixture
def mock_workato_webhook():
    """Create a mock WorkatoWebhook"""
    webhook = AsyncMock()
    webhook.send = AsyncMock()
    webhook.send_event = AsyncMock()
    return webhook


@pytest.fixture
def mock_error_logger():
    """Create a mock ErrorLogger"""
    logger = AsyncMock()
    logger.log_failed_retry = AsyncMock()
    logger.get_recent_errors = MagicMock(return_value=[])
    return logger


@pytest.fixture
def mock_video_recorder():
    """Create a mock VideoRecorder (deprecated)"""
    recorder = AsyncMock()
    recorder.start_recording = AsyncMock(return_value="http://test.example.com/recordings/test.mp4")
    recorder.stop_recording = AsyncMock(return_value=("http://test.example.com/recordings/test.mp4", 60))
    recorder.is_recording = MagicMock(return_value=False)
    recorder.get_recording_info = MagicMock(return_value=None)
    return recorder


@pytest.fixture
def mock_health_checker():
    """Create a mock DeviceHealthChecker"""
    checker = AsyncMock()
    checker.check_device_health = AsyncMock(return_value=True)
    checker.get_last_check_result = MagicMock(return_value=(True, datetime.now()))
    return checker


@pytest.fixture
def test_storage_path(tmp_path: Path) -> Path:
    """Create a temporary storage path for testing"""
    storage = tmp_path / "recordings"
    storage.mkdir(parents=True, exist_ok=True)
    return storage


@pytest.fixture
def sample_motion_event() -> dict:
    """Sample motion detected event"""
    return {
        "type": "event",
        "event": "motion_detected",
        "serialNumber": "T8600P1234567890",
        "deviceName": "Front Door Camera",
        "timestamp": datetime.now().isoformat()
    }


@pytest.fixture
def sample_offline_event() -> dict:
    """Sample device offline event"""
    return {
        "type": "event",
        "event": "device.disconnect",
        "serialNumber": "T8600P1234567890",
        "deviceName": "Front Door Camera",
        "timestamp": datetime.now().isoformat()
    }


@pytest.fixture
def sample_battery_event() -> dict:
    """Sample low battery event"""
    return {
        "type": "event",
        "event": "low_battery",
        "serialNumber": "T8600P1234567890",
        "deviceName": "Front Door Camera",
        "batteryValue": 15,
        "timestamp": datetime.now().isoformat()
    }


@pytest.fixture
def mock_camera_registry():
    """Create a mock CameraRegistry with test data"""
    registry = MagicMock(spec=CameraRegistry)

    # Mock camera data
    test_camera = CameraInfo(
        device_sn="T8600P1234567890",
        slack_channel="test-channel",
        latest_activity=get_brasilia_now(),
        state="closed"
    )

    registry.cameras = {"T8600P1234567890": test_camera}
    registry.get_camera = AsyncMock(return_value=test_camera)
    registry.update_activity = AsyncMock()
    registry.set_state = AsyncMock()
    registry.get_all_cameras = AsyncMock(return_value=[test_camera])
    registry.get_cameras_by_state = AsyncMock(return_value=[test_camera])
    registry.get_slack_channel = MagicMock(return_value="test-channel")

    return registry


@pytest.fixture
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
