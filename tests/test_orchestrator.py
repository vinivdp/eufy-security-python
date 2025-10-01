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

    # Verify all handlers are initialized
    assert orchestrator.motion_handler is not None
    assert orchestrator.offline_handler is not None
    assert orchestrator.battery_handler is not None


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
async def test_orchestrator_routes_offline_event(mock_config, sample_offline_event):
    """Test orchestrator routes offline events to offline handler"""
    orchestrator = EventOrchestrator(mock_config)

    # Mock offline handler
    orchestrator.offline_handler.on_disconnect = AsyncMock()

    # Route event
    await orchestrator._route_event(sample_offline_event)

    # Verify handler was called
    orchestrator.offline_handler.on_disconnect.assert_called_once_with(
        sample_offline_event
    )


@pytest.mark.asyncio
async def test_orchestrator_routes_battery_event(mock_config, sample_battery_event):
    """Test orchestrator routes battery events to battery handler"""
    orchestrator = EventOrchestrator(mock_config)

    # Mock battery handler
    orchestrator.battery_handler.on_low_battery = AsyncMock()

    # Route event
    await orchestrator._route_event(sample_battery_event)

    # Verify handler was called
    orchestrator.battery_handler.on_low_battery.assert_called_once_with(
        sample_battery_event
    )


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
    assert orchestrator.motion_handler.motion_timeout == mock_config.recording.motion_timeout_seconds
    assert orchestrator.motion_handler.max_duration == mock_config.recording.max_duration_seconds
    assert orchestrator.offline_handler.debounce_seconds == mock_config.alerts.offline.debounce_seconds
    assert orchestrator.battery_handler.cooldown_hours == mock_config.alerts.battery.cooldown_hours
