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
    """Test motion handler stays open when already open (no state change)"""
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

    # Verify webhook was sent
    mock_workato_webhook.send_event.assert_called_once()

    # Verify state was NOT updated (camera already open, no transition)
    mock_camera_registry.set_state.assert_not_called()

    # Verify activity was updated
    mock_camera_registry.update_activity.assert_called_once()

    # Verify event data shows state=open
    call_args = mock_workato_webhook.send_event.call_args[0][0]
    assert isinstance(call_args, MotionDetectedEvent)
    assert call_args.state == "open"


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
