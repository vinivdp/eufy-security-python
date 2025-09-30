"""Integration tests for end-to-end workflows"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.orchestrator import EventOrchestrator
from src.models.events import MotionDetectedEvent, MotionStoppedEvent


@pytest.mark.asyncio
async def test_motion_detection_workflow(mock_config):
    """Test complete motion detection workflow"""
    orchestrator = EventOrchestrator(mock_config)

    # Mock external dependencies
    orchestrator.websocket_client.connect = AsyncMock()
    orchestrator.websocket_client.send_command = AsyncMock()

    with patch.object(orchestrator.video_recorder, '_start_ffmpeg_process') as mock_start, \
         patch.object(orchestrator.video_recorder, '_stop_ffmpeg_process') as mock_stop, \
         patch.object(orchestrator.workato_webhook, 'send') as mock_webhook:

        mock_process = MagicMock()
        mock_start.return_value = mock_process
        mock_webhook.return_value = {"success": True}

        # Start orchestrator
        await orchestrator.start()

        # Simulate motion detected event
        motion_event = {
            "type": "event",
            "event": "motion_detected",
            "serialNumber": "T8600P1234567890",
            "deviceName": "Front Door Camera"
        }

        await orchestrator._route_event(motion_event)

        # Wait a bit for async processing
        await asyncio.sleep(0.1)

        # Verify recording started
        assert orchestrator.video_recorder.is_recording("T8600P1234567890")

        # Verify webhook was sent
        assert mock_webhook.call_count >= 1

        # Verify webhook payload
        call_args = mock_webhook.call_args_list[0][0][0]
        assert call_args["event"] == "motion_detected"
        assert call_args["device_sn"] == "T8600P1234567890"
        assert "video_url" in call_args

        # Stop recording
        result = await orchestrator.video_recorder.stop_recording("T8600P1234567890")
        assert result is not None

        # Stop orchestrator
        orchestrator.websocket_client.disconnect = AsyncMock()
        await orchestrator.stop()


@pytest.mark.asyncio
async def test_camera_offline_workflow(mock_config):
    """Test complete camera offline workflow"""
    orchestrator = EventOrchestrator(mock_config)

    with patch.object(orchestrator.workato_webhook, 'send') as mock_webhook:
        mock_webhook.return_value = {"success": True}

        # Simulate disconnect event
        disconnect_event = {
            "type": "event",
            "event": "device.disconnect",
            "serialNumber": "T8600P1234567890",
            "deviceName": "Front Door Camera"
        }

        await orchestrator._route_event(disconnect_event)

        # Wait for debounce (using config value from mock_config - 5 seconds)
        await asyncio.sleep(5.2)

        # Verify webhook was sent
        assert mock_webhook.call_count >= 1

        # Verify it's tracked as offline
        offline_devices = orchestrator.offline_handler.get_offline_devices()
        assert len(offline_devices) == 1
        assert offline_devices[0]["device_sn"] == "T8600P1234567890"


@pytest.mark.asyncio
async def test_low_battery_workflow(mock_config):
    """Test complete low battery workflow"""
    orchestrator = EventOrchestrator(mock_config)

    with patch.object(orchestrator.workato_webhook, 'send') as mock_webhook:
        mock_webhook.return_value = {"success": True}

        # Simulate low battery event
        battery_event = {
            "type": "event",
            "event": "low_battery",
            "serialNumber": "T8600P1234567890",
            "deviceName": "Front Door Camera",
            "batteryValue": 15
        }

        await orchestrator._route_event(battery_event)

        # Wait a bit for async processing
        await asyncio.sleep(0.05)

        # Verify webhook was sent
        assert mock_webhook.call_count >= 1

        # Verify webhook payload
        call_args = mock_webhook.call_args_list[0][0][0]
        assert call_args["event"] == "low_battery"
        assert call_args["device_sn"] == "T8600P1234567890"
        assert call_args["battery_level"] == 15


@pytest.mark.asyncio
async def test_multiple_devices_simultaneously(mock_config):
    """Test handling multiple devices simultaneously"""
    orchestrator = EventOrchestrator(mock_config)

    orchestrator.websocket_client.send_command = AsyncMock()

    with patch.object(orchestrator.video_recorder, '_start_ffmpeg_process') as mock_start, \
         patch.object(orchestrator.workato_webhook, 'send') as mock_webhook:

        mock_process = MagicMock()
        mock_start.return_value = mock_process
        mock_webhook.return_value = {"success": True}

        # Motion from device 1
        motion_event1 = {
            "type": "event",
            "event": "motion_detected",
            "serialNumber": "DEVICE001",
        }

        # Motion from device 2
        motion_event2 = {
            "type": "event",
            "event": "motion_detected",
            "serialNumber": "DEVICE002",
        }

        # Process both events
        await orchestrator._route_event(motion_event1)
        await orchestrator._route_event(motion_event2)

        await asyncio.sleep(0.1)

        # Verify both recordings are active
        assert orchestrator.video_recorder.is_recording("DEVICE001")
        assert orchestrator.video_recorder.is_recording("DEVICE002")

        # Verify webhooks sent for both
        assert mock_webhook.call_count >= 2


@pytest.mark.asyncio
async def test_error_recovery(mock_config):
    """Test system recovers from errors"""
    orchestrator = EventOrchestrator(mock_config)

    # Mock webhook to fail first time, succeed second time
    with patch.object(orchestrator.workato_webhook, 'send') as mock_webhook:
        mock_webhook.side_effect = [
            Exception("Network error"),
            Exception("Network error"),
            Exception("Network error"),  # All retries fail
        ]

        # Simulate event
        motion_event = {
            "type": "event",
            "event": "motion_detected",
            "serialNumber": "T8600P1234567890",
        }

        # Should not crash the system
        with patch.object(orchestrator.video_recorder, '_start_ffmpeg_process'):
            orchestrator.websocket_client.send_command = AsyncMock()
            await orchestrator._route_event(motion_event)

        await asyncio.sleep(0.1)

        # Error should be logged
        errors = orchestrator.error_logger.get_recent_errors()
        assert len(errors) > 0


@pytest.mark.asyncio
async def test_motion_timeout_integration(mock_config):
    """Test motion timeout stops recording"""
    # Use very short timeout for test
    mock_config.recording.motion_timeout_seconds = 0.1

    orchestrator = EventOrchestrator(mock_config)
    orchestrator.websocket_client.send_command = AsyncMock()

    with patch.object(orchestrator.video_recorder, '_start_ffmpeg_process') as mock_start, \
         patch.object(orchestrator.video_recorder, '_stop_ffmpeg_process') as mock_stop, \
         patch.object(orchestrator.workato_webhook, 'send') as mock_webhook:

        mock_process = MagicMock()
        mock_start.return_value = mock_process
        mock_webhook.return_value = {"success": True}

        # Motion detected
        motion_event = {
            "type": "event",
            "event": "motion_detected",
            "serialNumber": "T8600P1234567890",
        }

        await orchestrator._route_event(motion_event)
        await asyncio.sleep(0.05)

        # Recording should be active
        assert orchestrator.video_recorder.is_recording("T8600P1234567890")

        # Wait for timeout
        await asyncio.sleep(0.15)

        # Recording should have stopped
        assert not orchestrator.video_recorder.is_recording("T8600P1234567890")

        # Motion stopped webhook should have been sent
        assert mock_webhook.call_count >= 2
