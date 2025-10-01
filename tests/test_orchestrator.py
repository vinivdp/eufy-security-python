"""Tests for event orchestrator"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.orchestrator import EventOrchestrator


@pytest.mark.asyncio
async def test_orchestrator_initialization(mock_config):
    """Test orchestrator initializes all components"""
    orchestrator = EventOrchestrator(mock_config)

    # Verify all services are initialized
    assert orchestrator.workato_webhook is not None
    assert orchestrator.error_logger is not None
    assert orchestrator.websocket_client is not None
    assert orchestrator.health_checker is not None
    assert orchestrator.camera_registry is not None
    assert orchestrator.state_timeout_checker is not None

    # Verify motion handler is initialized (offline/battery handlers deprecated)
    assert orchestrator.motion_handler is not None


@pytest.mark.asyncio
async def test_orchestrator_start(mock_config):
    """Test orchestrator starts successfully"""
    orchestrator = EventOrchestrator(mock_config)

    # Mock websocket connect
    orchestrator.websocket_client.connect = AsyncMock()

    await orchestrator.start()

    # Verify websocket was connected
    orchestrator.websocket_client.connect.assert_called_once()

    # Verify running flag is set
    assert orchestrator._running is True


@pytest.mark.asyncio
async def test_orchestrator_stop(mock_config):
    """Test orchestrator stops successfully"""
    orchestrator = EventOrchestrator(mock_config)

    # Mock dependencies
    orchestrator.websocket_client.connect = AsyncMock()
    orchestrator.websocket_client.disconnect = AsyncMock()

    # Start first
    await orchestrator.start()
    assert orchestrator._running is True

    # Stop
    await orchestrator.stop()

    # Verify websocket was disconnected
    orchestrator.websocket_client.disconnect.assert_called_once()

    # Verify running flag is cleared
    assert orchestrator._running is False


@pytest.mark.asyncio
async def test_orchestrator_routes_motion_event(mock_config, sample_motion_event):
    """Test orchestrator routes motion events to motion handler"""
    orchestrator = EventOrchestrator(mock_config)

    # Mock motion handler
    orchestrator.motion_handler.on_motion_detected = AsyncMock()

    # Route event
    await orchestrator._route_event(sample_motion_event)

    # Verify handler was called
    orchestrator.motion_handler.on_motion_detected.assert_called_once_with(
        sample_motion_event
    )


@pytest.mark.asyncio
async def test_orchestrator_ignores_offline_event(mock_config, sample_offline_event):
    """Test orchestrator ignores offline events (now polling-based)"""
    orchestrator = EventOrchestrator(mock_config)

    # Route event - should be ignored
    await orchestrator._route_event(sample_offline_event)

    # No handler should be called (offline detection is now polling-based)
    # Just verify no exceptions raised


@pytest.mark.asyncio
async def test_orchestrator_ignores_battery_event(mock_config, sample_battery_event):
    """Test orchestrator ignores battery events (now polling-based)"""
    orchestrator = EventOrchestrator(mock_config)

    # Route event - should be ignored
    await orchestrator._route_event(sample_battery_event)

    # No handler should be called (battery detection is now polling-based)
    # Just verify no exceptions raised


@pytest.mark.asyncio
async def test_orchestrator_handles_unknown_event(mock_config):
    """Test orchestrator handles unknown event gracefully"""
    orchestrator = EventOrchestrator(mock_config)

    unknown_event = {
        "type": "event",
        "event": "unknown_event",
        "serialNumber": "T8600P1234567890"
    }

    # Should not raise exception
    await orchestrator._route_event(unknown_event)


@pytest.mark.asyncio
async def test_orchestrator_error_handling(mock_config):
    """Test orchestrator handles errors in event routing"""
    orchestrator = EventOrchestrator(mock_config)

    # Mock handler that raises exception
    orchestrator.motion_handler.on_motion_detected = AsyncMock(
        side_effect=Exception("Handler error")
    )

    motion_event = {
        "type": "event",
        "event": "motion_detected",
        "serialNumber": "T8600P1234567890"
    }

    # Should log error but not raise exception
    await orchestrator._route_event(motion_event)

    # Error should be logged to error logger
    assert len(orchestrator.error_logger.get_recent_errors()) > 0


@pytest.mark.asyncio
async def test_orchestrator_config_injection(mock_config):
    """Test orchestrator correctly uses config values"""
    orchestrator = EventOrchestrator(mock_config)

    # Verify config was passed to components
    assert orchestrator.health_checker.polling_interval_minutes == mock_config.alerts.offline.polling_interval_minutes
    assert orchestrator.health_checker.failure_threshold == mock_config.alerts.offline.failure_threshold
    assert orchestrator.health_checker.battery_threshold_percent == mock_config.alerts.offline.battery_threshold_percent
    assert orchestrator.state_timeout_checker.timeout_minutes == mock_config.motion.state_timeout_minutes
