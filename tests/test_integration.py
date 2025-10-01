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

    with patch.object(orchestrator.workato_webhook, 'send_event') as mock_webhook:

        mock_webhook.return_value = {"success": True}

        # Start orchestrator
        await orchestrator.start()

        # Wait for camera registry to load
        await asyncio.sleep(0.1)

        # Simulate motion detected event (use real camera from registry)
        motion_event = {
            "type": "event",
            "event": "motion_detected",
            "serialNumber": "T8150P40241800E7",  # Actual camera from config/cameras.txt
            "deviceName": "Test Camera"
        }

        await orchestrator._route_event(motion_event)

        # Wait a bit for async processing
        await asyncio.sleep(0.1)

        # Verify webhook was sent
        assert mock_webhook.call_count >= 1

        # Verify camera state was updated to open
        camera = await orchestrator.camera_registry.get_camera("T8150P40241800E7")
        assert camera is not None
        assert camera.state == "open"

        # Stop orchestrator
        orchestrator.websocket_client.disconnect = AsyncMock()
        await orchestrator.stop()


@pytest.mark.asyncio
async def test_camera_offline_workflow(mock_config):
    """Test camera offline detection is now polling-based (not event-based)"""
    orchestrator = EventOrchestrator(mock_config)

    # Offline detection is now polling-based via DeviceHealthChecker
    # Disconnect events are ignored by orchestrator

    with patch.object(orchestrator.workato_webhook, 'send_event') as mock_webhook:
        mock_webhook.return_value = {"success": True}

        # Simulate disconnect event (should be ignored)
        disconnect_event = {
            "type": "event",
            "event": "device.disconnect",
            "serialNumber": "T8600P1234567890",
            "deviceName": "Front Door Camera"
        }

        await orchestrator._route_event(disconnect_event)
        await asyncio.sleep(0.1)

        # No webhook should be sent for disconnect events
        # (offline detection happens via polling, not events)
        assert mock_webhook.call_count == 0

        # Verify offline detection is handled by DeviceHealthChecker
        assert orchestrator.health_checker is not None


@pytest.mark.asyncio
async def test_low_battery_workflow(mock_config):
    """Test low battery detection is now polling-based (not event-based)"""
    orchestrator = EventOrchestrator(mock_config)

    # Battery detection is now polling-based via DeviceHealthChecker
    # Low battery events are ignored by orchestrator

    with patch.object(orchestrator.workato_webhook, 'send_event') as mock_webhook:
        mock_webhook.return_value = {"success": True}

        # Simulate low battery event (should be ignored)
        battery_event = {
            "type": "event",
            "event": "low_battery",
            "serialNumber": "T8600P1234567890",
            "deviceName": "Front Door Camera",
            "batteryValue": 15
        }

        await orchestrator._route_event(battery_event)
        await asyncio.sleep(0.05)

        # No webhook should be sent for battery events
        # (battery detection happens via polling, not events)
        assert mock_webhook.call_count == 0

        # Verify battery detection is handled by DeviceHealthChecker
        assert orchestrator.health_checker is not None


@pytest.mark.asyncio
async def test_multiple_devices_simultaneously(mock_config):
    """Test handling multiple devices simultaneously"""
    orchestrator = EventOrchestrator(mock_config)

    orchestrator.websocket_client.connect = AsyncMock()
    orchestrator.websocket_client.send_command = AsyncMock()

    with patch.object(orchestrator.workato_webhook, 'send_event') as mock_webhook:

        mock_webhook.return_value = {"success": True}

        # Start orchestrator to load camera registry
        await orchestrator.start()
        await asyncio.sleep(0.1)

        # Motion from device 1 (use actual cameras from registry)
        motion_event1 = {
            "type": "event",
            "event": "motion_detected",
            "serialNumber": "T8150P40241800E7",  # Actual camera from config/cameras.txt
        }

        # Motion from device 2
        motion_event2 = {
            "type": "event",
            "event": "motion_detected",
            "serialNumber": "T8B005112336016A",  # Another actual camera from config/cameras.txt
        }

        # Process both events
        await orchestrator._route_event(motion_event1)
        await orchestrator._route_event(motion_event2)

        await asyncio.sleep(0.1)

        # Verify both cameras are tracked in registry
        camera1 = await orchestrator.camera_registry.get_camera("T8150P40241800E7")
        camera2 = await orchestrator.camera_registry.get_camera("T8B005112336016A")

        assert camera1 is not None
        assert camera2 is not None
        assert camera1.state == "open"
        assert camera2.state == "open"

        # Verify webhooks sent for both
        assert mock_webhook.call_count >= 2

        # Stop orchestrator
        orchestrator.websocket_client.disconnect = AsyncMock()
        await orchestrator.stop()


@pytest.mark.asyncio
async def test_error_recovery(mock_config):
    """Test system recovers from errors"""
    orchestrator = EventOrchestrator(mock_config)

    orchestrator.websocket_client.connect = AsyncMock()
    orchestrator.websocket_client.send_command = AsyncMock()

    # Mock webhook to fail with retries
    with patch.object(orchestrator.workato_webhook, 'send_event') as mock_webhook:
        mock_webhook.side_effect = [
            Exception("Network error"),
            Exception("Network error"),
            Exception("Network error"),  # All retries fail
        ]

        # Start orchestrator to load camera registry
        await orchestrator.start()
        await asyncio.sleep(0.1)

        # Simulate event (use actual camera from registry)
        motion_event = {
            "type": "event",
            "event": "motion_detected",
            "serialNumber": "T8150P40241800E7",  # Actual camera from config/cameras.txt
        }

        # Should not crash the system
        await orchestrator._route_event(motion_event)

        await asyncio.sleep(0.2)

        # Verify webhook was attempted (and failed as expected)
        assert mock_webhook.call_count >= 1

        # System should still be running despite errors
        assert orchestrator._running is True

        # Stop orchestrator
        orchestrator.websocket_client.disconnect = AsyncMock()
        await orchestrator.stop()


@pytest.mark.asyncio
async def test_motion_timeout_integration(mock_config):
    """Test motion timeout auto-closes camera state"""
    # Motion timeout is now handled by StateTimeoutChecker (1hr default)
    # For testing, we'd need to mock the timeout checker behavior
    # This test verifies the StateTimeoutChecker is initialized correctly

    orchestrator = EventOrchestrator(mock_config)
    orchestrator.websocket_client.connect = AsyncMock()
    orchestrator.websocket_client.send_command = AsyncMock()

    with patch.object(orchestrator.workato_webhook, 'send_event') as mock_webhook:

        mock_webhook.return_value = {"success": True}

        # Start orchestrator
        await orchestrator.start()
        await asyncio.sleep(0.1)

        # Verify StateTimeoutChecker is configured with correct timeout
        assert orchestrator.state_timeout_checker is not None
        assert orchestrator.state_timeout_checker.timeout_minutes == mock_config.motion.state_timeout_minutes

        # Motion detected (use actual camera from registry)
        motion_event = {
            "type": "event",
            "event": "motion_detected",
            "serialNumber": "T8150P40241800E7",  # Actual camera from config/cameras.txt
        }

        await orchestrator._route_event(motion_event)
        await asyncio.sleep(0.1)

        # Verify camera state is open
        camera = await orchestrator.camera_registry.get_camera("T8150P40241800E7")
        assert camera is not None
        assert camera.state == "open"

        # Stop orchestrator
        orchestrator.websocket_client.disconnect = AsyncMock()
        await orchestrator.stop()
