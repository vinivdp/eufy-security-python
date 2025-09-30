"""Tests for event handlers"""

import asyncio
import pytest
from datetime import datetime
from unittest.mock import AsyncMock

from src.handlers.motion_handler import MotionAlarmHandler
from src.handlers.offline_handler import OfflineAlarmHandler
from src.handlers.battery_handler import BatteryAlarmHandler
from src.models.events import MotionDetectedEvent, MotionStoppedEvent


@pytest.mark.asyncio
async def test_motion_handler_start_recording(
    mock_video_recorder,
    mock_workato_webhook,
    mock_error_logger,
    mock_websocket_client,
    sample_motion_event
):
    """Test motion handler starts recording on motion detected"""
    handler = MotionAlarmHandler(
        video_recorder=mock_video_recorder,
        workato_webhook=mock_workato_webhook,
        error_logger=mock_error_logger,
        websocket_client=mock_websocket_client,
        motion_timeout_seconds=60,
        max_duration_seconds=900,
    )

    await handler.on_motion_detected(sample_motion_event)

    # Verify recording was started
    mock_video_recorder.start_recording.assert_called_once_with(
        sample_motion_event["serialNumber"]
    )

    # Verify webhook was sent
    mock_workato_webhook.send_event.assert_called_once()

    # Verify event data
    call_args = mock_workato_webhook.send_event.call_args[0][0]
    assert isinstance(call_args, MotionDetectedEvent)
    assert call_args.device_sn == sample_motion_event["serialNumber"]


@pytest.mark.asyncio
async def test_motion_handler_no_motion_timeout(
    mock_video_recorder,
    mock_workato_webhook,
    mock_error_logger,
    mock_websocket_client,
    sample_motion_event
):
    """Test motion handler stops recording after timeout"""
    handler = MotionAlarmHandler(
        video_recorder=mock_video_recorder,
        workato_webhook=mock_workato_webhook,
        error_logger=mock_error_logger,
        websocket_client=mock_websocket_client,
        motion_timeout_seconds=0.1,  # Short timeout for test
        max_duration_seconds=900,
    )

    await handler.on_motion_detected(sample_motion_event)

    # Wait for timeout
    await asyncio.sleep(0.2)

    # Verify recording was stopped
    mock_video_recorder.stop_recording.assert_called_once_with(
        sample_motion_event["serialNumber"]
    )

    # Verify webhook was sent (motion stopped)
    assert mock_workato_webhook.send_event.call_count == 2

    # Check second call was motion stopped
    second_call = mock_workato_webhook.send_event.call_args_list[1][0][0]
    assert isinstance(second_call, MotionStoppedEvent)


@pytest.mark.asyncio
async def test_motion_handler_reset_timeout_on_new_motion(
    mock_video_recorder,
    mock_workato_webhook,
    mock_error_logger,
    mock_websocket_client,
    sample_motion_event
):
    """Test motion handler resets timeout when new motion detected"""
    handler = MotionAlarmHandler(
        video_recorder=mock_video_recorder,
        workato_webhook=mock_workato_webhook,
        error_logger=mock_error_logger,
        websocket_client=mock_websocket_client,
        motion_timeout_seconds=0.2,
        max_duration_seconds=900,
    )

    # First motion
    await handler.on_motion_detected(sample_motion_event)

    # Wait half timeout
    await asyncio.sleep(0.1)

    # New motion resets timer
    await handler.on_motion_detected(sample_motion_event)

    # Wait original timeout duration
    await asyncio.sleep(0.15)

    # Should not have stopped yet (timer was reset)
    mock_video_recorder.stop_recording.assert_not_called()

    # Wait for new timeout to expire
    await asyncio.sleep(0.1)

    # Now it should stop
    mock_video_recorder.stop_recording.assert_called_once()


@pytest.mark.asyncio
async def test_offline_handler_debounce(
    mock_workato_webhook,
    mock_error_logger,
    sample_offline_event
):
    """Test offline handler debounces disconnect events"""
    handler = OfflineAlarmHandler(
        workato_webhook=mock_workato_webhook,
        error_logger=mock_error_logger,
        debounce_seconds=0.1,  # Short debounce for test
    )

    await handler.on_disconnect(sample_offline_event)

    # Should not send webhook immediately
    mock_workato_webhook.send_event.assert_not_called()

    # Wait for debounce
    await asyncio.sleep(0.15)

    # Now webhook should be sent
    mock_workato_webhook.send_event.assert_called_once()


@pytest.mark.asyncio
async def test_offline_handler_reconnect_cancels_alert(
    mock_workato_webhook,
    mock_error_logger,
    sample_offline_event
):
    """Test offline handler cancels alert if device reconnects"""
    handler = OfflineAlarmHandler(
        workato_webhook=mock_workato_webhook,
        error_logger=mock_error_logger,
        debounce_seconds=0.2,
    )

    # Disconnect
    await handler.on_disconnect(sample_offline_event)

    # Wait a bit
    await asyncio.sleep(0.1)

    # Reconnect before debounce expires
    reconnect_event = {
        "serialNumber": sample_offline_event["serialNumber"],
        "event": "device.connect"
    }
    await handler.on_reconnect(reconnect_event)

    # Wait for original debounce to expire
    await asyncio.sleep(0.15)

    # Webhook should not be sent
    mock_workato_webhook.send_event.assert_not_called()


@pytest.mark.asyncio
async def test_battery_handler_sends_alert(
    mock_workato_webhook,
    mock_error_logger,
    sample_battery_event
):
    """Test battery handler sends alert for low battery"""
    handler = BatteryAlarmHandler(
        workato_webhook=mock_workato_webhook,
        error_logger=mock_error_logger,
        cooldown_hours=24,
    )

    await handler.on_low_battery(sample_battery_event)

    # Verify webhook was sent
    mock_workato_webhook.send_event.assert_called_once()

    # Verify event data
    call_args = mock_workato_webhook.send_event.call_args[0][0]
    assert call_args.device_sn == sample_battery_event["serialNumber"]
    assert call_args.battery_level == sample_battery_event["batteryValue"]


@pytest.mark.asyncio
async def test_battery_handler_cooldown(
    mock_workato_webhook,
    mock_error_logger,
    sample_battery_event
):
    """Test battery handler respects cooldown period"""
    handler = BatteryAlarmHandler(
        workato_webhook=mock_workato_webhook,
        error_logger=mock_error_logger,
        cooldown_hours=1,
    )

    # First alert
    await handler.on_low_battery(sample_battery_event)
    assert mock_workato_webhook.send_event.call_count == 1

    # Second alert immediately after (should be blocked)
    await handler.on_low_battery(sample_battery_event)
    assert mock_workato_webhook.send_event.call_count == 1  # Still 1


@pytest.mark.asyncio
async def test_get_device_state(
    mock_video_recorder,
    mock_workato_webhook,
    mock_error_logger,
    mock_websocket_client,
    sample_motion_event
):
    """Test getting device state from motion handler"""
    handler = MotionAlarmHandler(
        video_recorder=mock_video_recorder,
        workato_webhook=mock_workato_webhook,
        error_logger=mock_error_logger,
        websocket_client=mock_websocket_client,
        motion_timeout_seconds=60,
        max_duration_seconds=900,
    )

    device_sn = sample_motion_event["serialNumber"]

    # No state initially
    state = handler.get_device_state(device_sn)
    assert state is None

    # Start recording
    await handler.on_motion_detected(sample_motion_event)

    # Check state
    state = handler.get_device_state(device_sn)
    assert state is not None
    assert state["device_sn"] == device_sn
    assert state["is_recording"] is True
    assert state["video_url"] is not None


@pytest.mark.asyncio
async def test_get_offline_devices(
    mock_workato_webhook,
    mock_error_logger,
    sample_offline_event
):
    """Test getting list of offline devices"""
    handler = OfflineAlarmHandler(
        workato_webhook=mock_workato_webhook,
        error_logger=mock_error_logger,
        debounce_seconds=0.1,
    )

    # No offline devices initially
    devices = handler.get_offline_devices()
    assert len(devices) == 0

    # Disconnect device
    await handler.on_disconnect(sample_offline_event)

    # Check offline devices
    devices = handler.get_offline_devices()
    assert len(devices) == 1
    assert devices[0]["device_sn"] == sample_offline_event["serialNumber"]


@pytest.mark.asyncio
async def test_get_battery_alerts(
    mock_workato_webhook,
    mock_error_logger,
    sample_battery_event
):
    """Test getting battery alert history"""
    handler = BatteryAlarmHandler(
        workato_webhook=mock_workato_webhook,
        error_logger=mock_error_logger,
        cooldown_hours=24,
    )

    # No alerts initially
    alerts = handler.get_battery_alerts()
    assert len(alerts) == 0

    # Send alert
    await handler.on_low_battery(sample_battery_event)

    # Check alerts
    alerts = handler.get_battery_alerts()
    assert len(alerts) == 1
    assert alerts[0]["device_sn"] == sample_battery_event["serialNumber"]
