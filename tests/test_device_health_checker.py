"""Tests for DeviceHealthChecker"""

import pytest
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

from src.services.device_health_checker import DeviceHealthChecker, OFFLINE_DEVICES_FILE
from src.services.camera_registry import get_brasilia_now
from src.services.connection_tracker import ConnectionTracker


@pytest.fixture
def mock_websocket_client():
    """Create a mock WebSocket client"""
    client = MagicMock()
    client.send_command = AsyncMock()
    return client


@pytest.fixture
def mock_camera_registry():
    """Create a mock camera registry"""
    registry = MagicMock()
    registry.get_all_cameras = AsyncMock(return_value=[])
    return registry


@pytest.fixture
def mock_workato_webhook():
    """Create a mock Workato webhook"""
    webhook = MagicMock()
    webhook.send_event = AsyncMock()
    return webhook


@pytest.fixture
def mock_error_logger():
    """Create a mock error logger"""
    logger = MagicMock()
    logger.log_failed_retry = AsyncMock()
    return logger


@pytest.fixture
def mock_connection_tracker():
    """Create a mock connection tracker"""
    tracker = MagicMock(spec=ConnectionTracker)
    tracker.is_connected = MagicMock(return_value=True)  # Default to connected
    return tracker


@pytest.fixture
def health_checker(mock_websocket_client, mock_camera_registry, mock_workato_webhook, mock_error_logger, mock_connection_tracker):
    """Create a DeviceHealthChecker instance"""
    # Clean up any existing offline devices file
    if OFFLINE_DEVICES_FILE.exists():
        OFFLINE_DEVICES_FILE.unlink()

    return DeviceHealthChecker(
        websocket_client=mock_websocket_client,
        camera_registry=mock_camera_registry,
        workato_webhook=mock_workato_webhook,
        error_logger=mock_error_logger,
        connection_tracker=mock_connection_tracker,
        polling_interval_minutes=5,
        failure_threshold=3,
        battery_threshold_percent=30,
        battery_cooldown_hours=24,
    )


def test_initialization(health_checker):
    """Test health checker initializes correctly"""
    assert health_checker.polling_interval_minutes == 5
    assert health_checker.failure_threshold == 3
    assert health_checker.battery_threshold_percent == 30
    assert health_checker.battery_cooldown_hours == 24
    assert isinstance(health_checker.offline_devices_timestamps, dict)
    assert isinstance(health_checker.failure_counts, dict)


def test_load_offline_devices_empty(health_checker):
    """Test loading offline devices when file doesn't exist"""
    devices = health_checker._load_offline_devices()
    assert devices == {}


def test_save_and_load_offline_devices(health_checker):
    """Test saving and loading offline devices"""
    # Add some offline devices
    now = get_brasilia_now()
    health_checker.offline_devices_timestamps["device1"] = now
    health_checker.offline_devices_timestamps["device2"] = now - timedelta(hours=12)

    # Save
    health_checker._save_offline_devices()

    # Verify file exists
    assert OFFLINE_DEVICES_FILE.exists()

    # Load in a new instance
    new_checker = DeviceHealthChecker(
        websocket_client=MagicMock(),
        camera_registry=MagicMock(),
        workato_webhook=MagicMock(),
        error_logger=MagicMock(),
        connection_tracker=MagicMock(spec=ConnectionTracker),
    )

    # Should have loaded the devices
    assert len(new_checker.offline_devices_timestamps) == 2
    assert "device1" in new_checker.offline_devices_timestamps
    assert "device2" in new_checker.offline_devices_timestamps

    # Cleanup
    OFFLINE_DEVICES_FILE.unlink()


@pytest.mark.asyncio
async def test_check_camera_health_success_regular_camera(health_checker, mock_websocket_client):
    """Test successful health check for regular camera (not standalone)"""
    # Mock successful response for regular camera
    mock_websocket_client.send_command.return_value = {
        "type": "result",
        "success": True,
        "result": {
            "properties": {
                "battery": 85
            }
        }
    }

    await health_checker._check_camera_health("T8410", "test-channel")

    # Should have called send_command once (device.get_properties)
    mock_websocket_client.send_command.assert_called_once()
    call_args = mock_websocket_client.send_command.call_args
    assert call_args[0][0] == "device.get_properties"
    assert call_args.kwargs["wait_response"] is True
    assert call_args.kwargs["timeout"] == 10.0


@pytest.mark.asyncio
async def test_check_camera_health_success_standalone_camera(health_checker, mock_websocket_client, mock_connection_tracker):
    """Test successful health check for standalone camera (T8B0* or T8150*)"""
    # Mock connection tracker showing device is connected
    mock_connection_tracker.is_connected.return_value = True

    # Mock device.get_properties for battery
    mock_websocket_client.send_command.return_value = {
        "type": "result",
        "success": True,
        "result": {
            "properties": {
                "battery": 85
            }
        }
    }

    await health_checker._check_camera_health("T8B00511242309F6", "test-channel")

    # Should have checked connection state
    mock_connection_tracker.is_connected.assert_called_with("T8B00511242309F6")

    # Should have called send_command once for device.get_properties
    mock_websocket_client.send_command.assert_called_once()
    call_args = mock_websocket_client.send_command.call_args
    assert call_args[0][0] == "device.get_properties"
    assert call_args[0][1]["serialNumber"] == "T8B00511242309F6"


@pytest.mark.asyncio
async def test_check_camera_health_standalone_camera_disconnected(health_checker, mock_websocket_client, mock_workato_webhook, mock_connection_tracker):
    """Test health check when standalone camera is offline (disconnected via WebSocket)"""
    # Mock connection tracker showing device is disconnected
    mock_connection_tracker.is_connected.return_value = False

    # First two failures - should NOT send alert
    await health_checker._check_camera_health("T8B00511242309F6", "test-channel")
    await health_checker._check_camera_health("T8B00511242309F6", "test-channel")
    mock_workato_webhook.send_event.assert_not_called()

    # Third failure - should send alert
    await health_checker._check_camera_health("T8B00511242309F6", "test-channel")
    mock_workato_webhook.send_event.assert_called_once()

    # Device should be in offline_devices_timestamps
    assert "T8B00511242309F6" in health_checker.offline_devices_timestamps
    assert health_checker.failure_counts["T8B00511242309F6"] == 3

    # Should not have called send_command since we detected disconnection early
    mock_websocket_client.send_command.assert_not_called()


@pytest.mark.asyncio
async def test_check_camera_health_device_not_found(health_checker, mock_websocket_client, mock_workato_webhook):
    """Test health check when device not found - requires failure threshold"""
    # Mock device_not_found response
    mock_websocket_client.send_command.return_value = {
        "type": "result",
        "success": False,
        "errorCode": "device_not_found"
    }

    # First two failures - should NOT send alert
    await health_checker._check_camera_health("OFFLINE_DEVICE", "test-channel")
    await health_checker._check_camera_health("OFFLINE_DEVICE", "test-channel")
    mock_workato_webhook.send_event.assert_not_called()

    # Third failure - should send alert
    await health_checker._check_camera_health("OFFLINE_DEVICE", "test-channel")
    mock_workato_webhook.send_event.assert_called_once()

    # Device should be in offline_devices_timestamps
    assert "OFFLINE_DEVICE" in health_checker.offline_devices_timestamps
    assert health_checker.failure_counts["OFFLINE_DEVICE"] == 3


@pytest.mark.asyncio
async def test_check_camera_health_skip_offline_cooldown(health_checker, mock_websocket_client):
    """Test health check skips devices in cooldown"""
    # Mark device as offline recently
    health_checker.offline_devices_timestamps["OFFLINE_DEVICE"] = get_brasilia_now()

    await health_checker._check_camera_health("OFFLINE_DEVICE", "test-channel")

    # Should NOT have called send_command
    mock_websocket_client.send_command.assert_not_called()


@pytest.mark.asyncio
async def test_check_camera_health_retry_after_24h(health_checker, mock_websocket_client):
    """Test health check retries device after 24 hours"""
    # Mark device as offline 25 hours ago (using a regular camera serial)
    health_checker.offline_devices_timestamps["T8410OLD"] = get_brasilia_now() - timedelta(hours=25)

    # Mock successful response (device is back online)
    mock_websocket_client.send_command.return_value = {
        "type": "result",
        "success": True,
        "result": {
            "properties": {
                "battery": 90
            }
        }
    }

    await health_checker._check_camera_health("T8410OLD", "test-channel")

    # Should have called send_command once
    mock_websocket_client.send_command.assert_called_once()

    # Device should be removed from offline list
    assert "T8410OLD" not in health_checker.offline_devices_timestamps


@pytest.mark.asyncio
async def test_handle_failure_increments_count(health_checker):
    """Test failure handling increments failure count"""
    await health_checker._handle_failure("TEST_DEVICE", "test-channel", "timeout")

    assert health_checker.failure_counts["TEST_DEVICE"] == 1

    await health_checker._handle_failure("TEST_DEVICE", "test-channel", "timeout")

    assert health_checker.failure_counts["TEST_DEVICE"] == 2


@pytest.mark.asyncio
async def test_handle_failure_sends_alert_at_threshold(health_checker, mock_workato_webhook):
    """Test failure sends alert when threshold reached"""
    # Fail 3 times to reach threshold
    for _ in range(3):
        await health_checker._handle_failure("TEST_DEVICE", "test-channel", "timeout")

    # Should have sent offline alert
    mock_workato_webhook.send_event.assert_called_once()

    # Device should be in offline list
    assert "TEST_DEVICE" in health_checker.offline_devices_timestamps


@pytest.mark.asyncio
async def test_handle_failure_no_duplicate_alert(health_checker, mock_workato_webhook):
    """Test failure doesn't send duplicate alerts"""
    # Fail 3 times to reach threshold
    for _ in range(3):
        await health_checker._handle_failure("TEST_DEVICE", "test-channel", "timeout")

    # Reset mock to track new calls
    mock_workato_webhook.send_event.reset_mock()

    # Fail again
    await health_checker._handle_failure("TEST_DEVICE", "test-channel", "timeout")

    # Should NOT send another alert
    mock_workato_webhook.send_event.assert_not_called()


@pytest.mark.asyncio
async def test_handle_online_response_resets_failure(health_checker):
    """Test online response resets failure count"""
    # Add some failures
    health_checker.failure_counts["TEST_DEVICE"] = 2

    response = {
        "type": "result",
        "success": True,
        "result": {
            "properties": {
                "battery": 75
            }
        }
    }

    await health_checker._handle_online_response("TEST_DEVICE", "test-channel", response)

    # Failure count should be cleared
    assert "TEST_DEVICE" not in health_checker.failure_counts


@pytest.mark.asyncio
async def test_handle_online_response_removes_from_offline(health_checker):
    """Test online response removes device from offline list"""
    # Mark as offline
    health_checker.offline_devices_timestamps["TEST_DEVICE"] = get_brasilia_now()

    response = {
        "type": "result",
        "success": True,
        "result": {
            "properties": {
                "battery": 80
            }
        }
    }

    await health_checker._handle_online_response("TEST_DEVICE", "test-channel", response)

    # Should be removed from offline list
    assert "TEST_DEVICE" not in health_checker.offline_devices_timestamps


@pytest.mark.asyncio
async def test_handle_online_response_low_battery_alert(health_checker, mock_workato_webhook):
    """Test online response sends low battery alert"""
    response = {
        "type": "result",
        "success": True,
        "result": {
            "properties": {
                "battery": 15  # Below threshold of 30
            }
        }
    }

    await health_checker._handle_online_response("TEST_DEVICE", "test-channel", response)

    # Should send low battery alert
    mock_workato_webhook.send_event.assert_called_once()


@pytest.mark.asyncio
async def test_low_battery_alert_cooldown(health_checker, mock_workato_webhook):
    """Test low battery alert respects cooldown"""
    # Send first alert
    await health_checker._send_low_battery_alert("TEST_DEVICE", "test-channel", 15)
    assert mock_workato_webhook.send_event.call_count == 1

    # Try to send again immediately
    mock_workato_webhook.send_event.reset_mock()
    await health_checker._send_low_battery_alert("TEST_DEVICE", "test-channel", 10)

    # Should NOT send (cooldown)
    mock_workato_webhook.send_event.assert_not_called()
