"""Tests for StateTimeoutChecker"""

import pytest
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

from src.services.state_timeout_checker import StateTimeoutChecker
from src.services.camera_registry import CameraInfo, get_brasilia_now
from src.models.events import MotionStoppedEvent


@pytest.mark.asyncio
async def test_state_timeout_checker_includes_event_log(
    mock_camera_registry,
    mock_workato_webhook,
    mock_error_logger,
):
    """Test that StateTimeoutChecker includes event log when closing camera"""
    # Create mock motion handler with event log
    mock_motion_handler = MagicMock()
    mock_event_log = [
        {
            "timestamp": "2025-01-30T14:30:00-03:00",
            "event_type": "motion_detected",
            "serial_number": "T8600P1234567890",
        },
        {
            "timestamp": "2025-01-30T14:35:00-03:00",
            "event_type": "motion_detected",
            "serial_number": "T8600P1234567890",
        },
    ]
    mock_motion_handler.get_and_clear_event_log = MagicMock(return_value=mock_event_log)

    # Create camera that's been open for over 1 hour
    old_activity = get_brasilia_now() - timedelta(minutes=65)
    open_camera = CameraInfo(
        device_sn="T8600P1234567890",
        slack_channel="test-channel",
        latest_activity=old_activity,
        state="open"
    )

    mock_camera_registry.get_camera = AsyncMock(return_value=open_camera)
    mock_camera_registry.get_cameras_by_state = AsyncMock(return_value=[open_camera])

    # Create checker with motion_handler
    checker = StateTimeoutChecker(
        camera_registry=mock_camera_registry,
        workato_webhook=mock_workato_webhook,
        error_logger=mock_error_logger,
        motion_handler=mock_motion_handler,
        timeout_minutes=60,
        check_interval_seconds=60,
    )

    # Manually trigger timeout check
    await checker._check_timeouts()

    # Verify state was updated to closed
    mock_camera_registry.set_state.assert_called_once_with("T8600P1234567890", "closed")

    # Verify motion_handler.get_and_clear_event_log was called
    mock_motion_handler.get_and_clear_event_log.assert_called_once_with("T8600P1234567890")

    # Verify webhook was sent with event log
    mock_workato_webhook.send_event.assert_called_once()
    call_args = mock_workato_webhook.send_event.call_args[0][0]

    assert isinstance(call_args, MotionStoppedEvent)
    assert call_args.device_sn == "T8600P1234567890"
    assert call_args.state == "closed"
    assert call_args.event_log == mock_event_log
    assert len(call_args.event_log) == 2


@pytest.mark.asyncio
async def test_state_timeout_checker_no_timeout(
    mock_camera_registry,
    mock_workato_webhook,
    mock_error_logger,
):
    """Test that StateTimeoutChecker doesn't close cameras with recent activity"""
    mock_motion_handler = MagicMock()

    # Create camera with recent activity (30 minutes ago)
    recent_activity = get_brasilia_now() - timedelta(minutes=30)
    open_camera = CameraInfo(
        device_sn="T8600P1234567890",
        slack_channel="test-channel",
        latest_activity=recent_activity,
        state="open"
    )

    mock_camera_registry.get_cameras_by_state = AsyncMock(return_value=[open_camera])

    # Create checker
    checker = StateTimeoutChecker(
        camera_registry=mock_camera_registry,
        workato_webhook=mock_workato_webhook,
        error_logger=mock_error_logger,
        motion_handler=mock_motion_handler,
        timeout_minutes=60,
        check_interval_seconds=60,
    )

    # Manually trigger timeout check
    await checker._check_timeouts()

    # Verify state was NOT updated (no timeout reached)
    mock_camera_registry.set_state.assert_not_called()

    # Verify NO webhook was sent
    mock_workato_webhook.send_event.assert_not_called()

    # Verify event log was NOT retrieved
    mock_motion_handler.get_and_clear_event_log.assert_not_called()


@pytest.mark.asyncio
async def test_state_timeout_checker_empty_event_log(
    mock_camera_registry,
    mock_workato_webhook,
    mock_error_logger,
):
    """Test that StateTimeoutChecker handles empty event log gracefully"""
    # Create mock motion handler with empty event log
    mock_motion_handler = MagicMock()
    mock_motion_handler.get_and_clear_event_log = MagicMock(return_value=[])

    # Create camera that's been open for over 1 hour
    old_activity = get_brasilia_now() - timedelta(minutes=65)
    open_camera = CameraInfo(
        device_sn="T8600P1234567890",
        slack_channel="test-channel",
        latest_activity=old_activity,
        state="open"
    )

    mock_camera_registry.get_camera = AsyncMock(return_value=open_camera)
    mock_camera_registry.get_cameras_by_state = AsyncMock(return_value=[open_camera])

    # Create checker
    checker = StateTimeoutChecker(
        camera_registry=mock_camera_registry,
        workato_webhook=mock_workato_webhook,
        error_logger=mock_error_logger,
        motion_handler=mock_motion_handler,
        timeout_minutes=60,
        check_interval_seconds=60,
    )

    # Manually trigger timeout check
    await checker._check_timeouts()

    # Verify webhook was sent with empty event log
    mock_workato_webhook.send_event.assert_called_once()
    call_args = mock_workato_webhook.send_event.call_args[0][0]

    assert isinstance(call_args, MotionStoppedEvent)
    assert call_args.event_log == []
