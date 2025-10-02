"""Tests for event handlers"""

import asyncio
import pytest
from datetime import datetime
from unittest.mock import AsyncMock

from src.handlers.motion_handler import MotionAlarmHandler
from src.models.events import MotionDetectedEvent, MotionStoppedEvent, get_brasilia_now


@pytest.mark.asyncio
async def test_motion_handler_closed_to_open(
    mock_camera_registry,
    mock_workato_webhook,
    mock_error_logger,
    sample_motion_event
):
    """Test motion handler transitions from closed to open"""
    handler = MotionAlarmHandler(
        camera_registry=mock_camera_registry,
        workato_webhook=mock_workato_webhook,
        error_logger=mock_error_logger,
    )

    await handler.on_motion_detected(sample_motion_event)

    # Verify webhook was sent
    mock_workato_webhook.send_event.assert_called_once()

    # Verify state was updated to open
    mock_camera_registry.set_state.assert_called_once_with(
        sample_motion_event["serialNumber"],
        "open"
    )

    # Verify activity was updated
    mock_camera_registry.update_activity.assert_called_once()

    # Verify event data
    call_args = mock_workato_webhook.send_event.call_args[0][0]
    assert isinstance(call_args, MotionDetectedEvent)
    assert call_args.device_sn == sample_motion_event["serialNumber"]
    assert call_args.state == "open"
    assert call_args.slack_channel == "test-channel"


@pytest.mark.asyncio
async def test_motion_handler_open_to_open(
    mock_camera_registry,
    mock_workato_webhook,
    mock_error_logger,
    sample_motion_event
):
    """Test motion handler stays open when already open (logs event, no webhook)"""
    # Configure camera as already open
    from src.services.camera_registry import CameraInfo
    open_camera = CameraInfo(
        device_sn="T8600P1234567890",
        slack_channel="test-channel",
        latest_activity=get_brasilia_now(),
        state="open"  # Already open
    )
    mock_camera_registry.get_camera = AsyncMock(return_value=open_camera)

    handler = MotionAlarmHandler(
        camera_registry=mock_camera_registry,
        workato_webhook=mock_workato_webhook,
        error_logger=mock_error_logger,
    )

    await handler.on_motion_detected(sample_motion_event)

    # Verify NO webhook was sent (OPEN → OPEN logs only)
    mock_workato_webhook.send_event.assert_not_called()

    # Verify state was NOT updated (camera already open, no transition)
    mock_camera_registry.set_state.assert_not_called()

    # Verify activity was updated
    mock_camera_registry.update_activity.assert_called_once()

    # Verify event was logged in buffer
    event_log = handler.get_and_clear_event_log(sample_motion_event["serialNumber"])
    assert len(event_log) == 1
    assert event_log[0]["event_type"] == sample_motion_event["event"]
    assert event_log[0]["serial_number"] == sample_motion_event["serialNumber"]
    assert "timestamp" in event_log[0]


@pytest.mark.asyncio
async def test_motion_handler_unknown_camera(
    mock_camera_registry,
    mock_workato_webhook,
    mock_error_logger,
    sample_motion_event
):
    """Test motion handler handles unknown camera gracefully"""
    # Configure registry to return None for unknown camera
    mock_camera_registry.get_camera = AsyncMock(return_value=None)

    handler = MotionAlarmHandler(
        camera_registry=mock_camera_registry,
        workato_webhook=mock_workato_webhook,
        error_logger=mock_error_logger,
    )

    await handler.on_motion_detected(sample_motion_event)

    # Should not send webhook for unknown camera
    mock_workato_webhook.send_event.assert_not_called()

    # Should not update state or activity
    mock_camera_registry.set_state.assert_not_called()
    mock_camera_registry.update_activity.assert_not_called()


@pytest.mark.asyncio
async def test_motion_handler_event_logging_lifecycle(
    mock_camera_registry,
    mock_workato_webhook,
    mock_error_logger,
):
    """Test motion handler logs all events during open/close cycle"""
    from src.services.camera_registry import CameraInfo

    # Start with closed camera
    closed_camera = CameraInfo(
        device_sn="T8600P1234567890",
        slack_channel="test-channel",
        latest_activity=get_brasilia_now(),
        state="closed"
    )
    mock_camera_registry.get_camera = AsyncMock(return_value=closed_camera)

    handler = MotionAlarmHandler(
        camera_registry=mock_camera_registry,
        workato_webhook=mock_workato_webhook,
        error_logger=mock_error_logger,
    )

    # First event: CLOSED → OPEN (initializes log, sends webhook)
    event1 = {
        "serialNumber": "T8600P1234567890",
        "deviceName": "Test Camera",
        "event": "motion_detected",
        "personDetected": False,
    }
    await handler.on_motion_detected(event1)
    assert mock_workato_webhook.send_event.call_count == 1

    # Switch camera to open for subsequent events
    open_camera = CameraInfo(
        device_sn="T8600P1234567890",
        slack_channel="test-channel",
        latest_activity=get_brasilia_now(),
        state="open"
    )
    mock_camera_registry.get_camera = AsyncMock(return_value=open_camera)

    # Second event: OPEN → OPEN (logs only, no webhook)
    event2 = {
        "serialNumber": "T8600P1234567890",
        "deviceName": "Test Camera",
        "event": "motion_detected",
        "personDetected": True,
        "personName": "John Doe",
    }
    await handler.on_motion_detected(event2)
    assert mock_workato_webhook.send_event.call_count == 1  # Still 1, no new webhook

    # Third event: OPEN → OPEN (logs only, no webhook)
    event3 = {
        "serialNumber": "T8600P1234567890",
        "deviceName": "Test Camera",
        "event": "motion_detected",
        "personDetected": False,
    }
    await handler.on_motion_detected(event3)
    assert mock_workato_webhook.send_event.call_count == 1  # Still 1, no new webhook

    # Get accumulated event log
    event_log = handler.get_and_clear_event_log("T8600P1234567890")

    # Should have logged all 3 events
    assert len(event_log) == 3
    assert event_log[0]["event_type"] == "motion_detected"
    assert event_log[0]["serial_number"] == "T8600P1234567890"
    assert "timestamp" in event_log[0]
    assert event_log[1]["event_type"] == "motion_detected"
    assert event_log[1]["serial_number"] == "T8600P1234567890"
    assert event_log[2]["event_type"] == "motion_detected"
    assert event_log[2]["serial_number"] == "T8600P1234567890"

    # Verify we only have timestamp, event_type, and serial_number (no person_detected, etc.)
    assert set(event_log[0].keys()) == {"timestamp", "event_type", "serial_number"}

    # Log should be cleared after retrieval
    event_log_again = handler.get_and_clear_event_log("T8600P1234567890")
    assert len(event_log_again) == 0
