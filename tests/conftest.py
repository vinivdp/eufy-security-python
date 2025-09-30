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
    RetryConfig,
    ErrorLoggingConfig,
    StorageConfig,
    AlertsConfig,
    BatteryAlertConfig,
    OfflineAlertConfig,
    LoggingConfig,
)


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
            max_duration_seconds=60,
            motion_timeout_seconds=5,
            snooze_duration_seconds=30,
            storage_path="./test_recordings",
            retention_days=7,
            video_codec="libx264",
            video_quality="medium"
        ),
        workato=WorkatoConfig(
            webhook_url="https://test.workato.com/webhook",
            timeout_seconds=10,
            rate_limit_per_second=10
        ),
        retry=RetryConfig(
            max_attempts=2,
            initial_delay=0.1,
            backoff_multiplier=2.0
        ),
        error_logging=ErrorLoggingConfig(
            send_to_workato=False,
            keep_in_memory=10
        ),
        storage=StorageConfig(
            cleanup_schedule="0 3 * * *",
            min_free_space_gb=1
        ),
        alerts=AlertsConfig(
            battery=BatteryAlertConfig(cooldown_hours=1),
            offline=OfflineAlertConfig(debounce_seconds=5)
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
    """Create a mock VideoRecorder"""
    recorder = AsyncMock()
    recorder.start_recording = AsyncMock(return_value="http://test.example.com/recordings/test.mp4")
    recorder.stop_recording = AsyncMock(return_value=("http://test.example.com/recordings/test.mp4", 60))
    recorder.is_recording = MagicMock(return_value=False)
    recorder.get_recording_info = MagicMock(return_value=None)
    return recorder


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
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
