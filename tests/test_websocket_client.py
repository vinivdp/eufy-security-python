"""Tests for WebSocket client"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from websockets.exceptions import ConnectionClosed

from src.clients.websocket_client import WebSocketClient


@pytest.fixture
def ws_client():
    """Create a WebSocket client instance"""
    return WebSocketClient(
        url="ws://test:3000/ws",
        reconnect_delay=0.1,
        heartbeat_interval=10.0
    )


@pytest.mark.asyncio
async def test_connect_success(ws_client):
    """Test successful WebSocket connection"""
    mock_ws = AsyncMock()

    with patch('websockets.connect', new_callable=AsyncMock, return_value=mock_ws) as mock_connect:
        await ws_client.connect()

        # Verify connection was made
        mock_connect.assert_called_once_with(
            "ws://test:3000/ws",
            ping_interval=10.0,
            ping_timeout=20.0
        )
        assert ws_client.ws == mock_ws


@pytest.mark.asyncio
async def test_connect_with_retry(ws_client):
    """Test connection retries on failure"""
    mock_ws = AsyncMock()

    with patch('websockets.connect', new_callable=AsyncMock) as mock_connect:
        # Fail twice, succeed third time
        mock_connect.side_effect = [
            ConnectionError("Connection failed"),
            ConnectionError("Connection failed"),
            mock_ws
        ]

        await ws_client.connect()

        # Should retry 3 times
        assert mock_connect.call_count == 3
        assert ws_client.ws == mock_ws


@pytest.mark.asyncio
async def test_connect_all_retries_fail(ws_client):
    """Test connection fails after all retries"""
    with patch('websockets.connect', new_callable=AsyncMock) as mock_connect:
        mock_connect.side_effect = ConnectionError("Connection failed")

        with pytest.raises(ConnectionError):
            await ws_client.connect()

        # Should try 3 times
        assert mock_connect.call_count == 3


@pytest.mark.asyncio
async def test_disconnect(ws_client):
    """Test disconnecting from WebSocket"""
    mock_ws = AsyncMock()
    ws_client.ws = mock_ws
    ws_client._running = True

    await ws_client.disconnect()

    # Verify close was called
    mock_ws.close.assert_called_once()
    assert ws_client.ws is None
    assert ws_client._running is False


@pytest.mark.asyncio
async def test_disconnect_with_reconnect_task(ws_client):
    """Test disconnecting cancels reconnect task"""
    mock_ws = AsyncMock()

    # Create a real task that we can cancel
    async def dummy_task():
        await asyncio.sleep(100)

    mock_task = asyncio.create_task(dummy_task())

    ws_client.ws = mock_ws
    ws_client._reconnect_task = mock_task

    await ws_client.disconnect()

    # Verify task was cancelled
    assert mock_task.cancelled()
    mock_ws.close.assert_called_once()


@pytest.mark.asyncio
async def test_send_command_success(ws_client):
    """Test sending command successfully"""
    mock_ws = AsyncMock()
    ws_client.ws = mock_ws

    await ws_client.send_command("device.start_livestream", {"serialNumber": "TEST123"})

    # Verify command was sent
    mock_ws.send.assert_called_once()
    sent_data = json.loads(mock_ws.send.call_args[0][0])
    assert sent_data["command"] == "device.start_livestream"
    assert sent_data["serialNumber"] == "TEST123"


@pytest.mark.asyncio
async def test_send_command_without_params(ws_client):
    """Test sending command without parameters"""
    mock_ws = AsyncMock()
    ws_client.ws = mock_ws

    await ws_client.send_command("get.status")

    # Verify command was sent
    mock_ws.send.assert_called_once()
    sent_data = json.loads(mock_ws.send.call_args[0][0])
    assert sent_data["command"] == "get.status"


@pytest.mark.asyncio
async def test_send_command_not_connected(ws_client):
    """Test sending command when not connected raises error"""
    ws_client.ws = None

    with pytest.raises(ConnectionError, match="WebSocket not connected"):
        await ws_client.send_command("test.command")


@pytest.mark.asyncio
async def test_send_command_with_retry(ws_client):
    """Test command retries on failure"""
    mock_ws = AsyncMock()
    ws_client.ws = mock_ws

    # Fail twice, succeed third time
    mock_ws.send.side_effect = [
        ConnectionError("Send failed"),
        ConnectionError("Send failed"),
        None  # Success
    ]

    await ws_client.send_command("test.command")

    # Should retry 3 times
    assert mock_ws.send.call_count == 3


def test_register_event_handler(ws_client):
    """Test registering event handlers"""
    async def handler(event):
        pass

    ws_client.on("motion detected", handler)

    assert "motion detected" in ws_client.event_handlers
    assert ws_client.event_handlers["motion detected"] == handler


def test_register_multiple_handlers(ws_client):
    """Test registering multiple event handlers"""
    async def handler1(event):
        pass

    async def handler2(event):
        pass

    ws_client.on("motion detected", handler1)
    ws_client.on("low battery", handler2)

    assert len(ws_client.event_handlers) == 2
    assert ws_client.event_handlers["motion detected"] == handler1
    assert ws_client.event_handlers["low battery"] == handler2


@pytest.mark.asyncio
async def test_handle_event_with_handler(ws_client):
    """Test handling event with registered handler"""
    handler_called = False
    received_event = None

    async def handler(event):
        nonlocal handler_called, received_event
        handler_called = True
        received_event = event

    ws_client.on("motion detected", handler)

    event = {"event": "motion detected", "serialNumber": "TEST123"}
    await ws_client._handle_event(event)

    assert handler_called
    assert received_event == event


@pytest.mark.asyncio
async def test_handle_event_nested_structure(ws_client):
    """Test handling event with nested eufy-security-ws structure"""
    handler_called = False
    received_event = None

    async def handler(event):
        nonlocal handler_called, received_event
        handler_called = True
        received_event = event

    ws_client.on("motion detected", handler)

    # Nested structure from eufy-security-ws
    event = {
        "type": "event",
        "event": {
            "source": "device",
            "event": "motion detected",
            "serialNumber": "T8B0051123360409",
            "state": True
        }
    }
    await ws_client._handle_event(event)

    assert handler_called
    # Handler should receive the inner event dict
    assert received_event == {
        "source": "device",
        "event": "motion detected",
        "serialNumber": "T8B0051123360409",
        "state": True
    }


@pytest.mark.asyncio
async def test_handle_event_without_handler(ws_client):
    """Test handling event without registered handler (should not crash)"""
    event = {"event": "unknown_event", "data": "test"}

    # Should not raise exception
    await ws_client._handle_event(event)


@pytest.mark.asyncio
async def test_handle_event_without_type(ws_client):
    """Test handling event without event type"""
    event = {"data": "test"}

    # Should not raise exception
    await ws_client._handle_event(event)


@pytest.mark.asyncio
async def test_handle_event_handler_exception(ws_client):
    """Test handling event when handler raises exception"""
    async def broken_handler(event):
        raise ValueError("Handler error")

    ws_client.on("test_event", broken_handler)

    event = {"event": "test_event", "data": "test"}

    # Should not propagate exception
    await ws_client._handle_event(event)


@pytest.mark.asyncio
async def test_handle_event_sync_handler(ws_client):
    """Test handling event with synchronous handler"""
    handler_called = False

    def sync_handler(event):
        nonlocal handler_called
        handler_called = True

    ws_client.on("test_event", sync_handler)

    event = {"event": "test_event"}
    await ws_client._handle_event(event)

    assert handler_called


# Note: start_listening tests are complex to mock properly without hanging
# We test the individual components (_handle_event, etc.) instead


@pytest.mark.asyncio
async def test_reconnect_closes_old_connection(ws_client):
    """Test reconnect closes old connection"""
    old_ws = AsyncMock()
    ws_client.ws = old_ws

    with patch.object(ws_client, 'connect', new_callable=AsyncMock):
        await ws_client._reconnect()

        # Old connection should be closed
        old_ws.close.assert_called_once()
        assert ws_client.ws is None


@pytest.mark.asyncio
async def test_reconnect_handles_close_exception(ws_client):
    """Test reconnect handles exception when closing old connection"""
    old_ws = AsyncMock()
    old_ws.close.side_effect = Exception("Close error")
    ws_client.ws = old_ws

    with patch.object(ws_client, 'connect', new_callable=AsyncMock):
        # Should not raise exception
        await ws_client._reconnect()

        assert ws_client.ws is None


@pytest.mark.asyncio
async def test_reconnect_with_delay(ws_client):
    """Test reconnect waits before reconnecting"""
    ws_client.reconnect_delay = 0.1

    with patch.object(ws_client, 'connect', new_callable=AsyncMock) as mock_connect:
        start_time = asyncio.get_event_loop().time()
        await ws_client._reconnect()
        elapsed = asyncio.get_event_loop().time() - start_time

        # Should wait at least reconnect_delay
        assert elapsed >= 0.1
        mock_connect.assert_called_once()


@pytest.mark.asyncio
async def test_reconnect_handles_connect_failure(ws_client):
    """Test reconnect handles connection failure"""
    with patch.object(ws_client, 'connect', new_callable=AsyncMock) as mock_connect:
        mock_connect.side_effect = ConnectionError("Reconnection failed")

        # Should not raise exception
        await ws_client._reconnect()


@pytest.mark.asyncio
async def test_send_command_with_response_success(ws_client):
    """Test sending command and receiving response"""
    mock_ws = AsyncMock()
    ws_client.ws = mock_ws

    # Simulate response coming back
    async def simulate_response():
        await asyncio.sleep(0.01)
        response = {
            "type": "result",
            "success": True,
            "messageId": None,  # Will be set by actual call
            "result": {"battery": 85}
        }
        # Find the pending request and resolve it
        if ws_client._pending_requests:
            message_id = list(ws_client._pending_requests.keys())[0]
            response["messageId"] = message_id
            await ws_client._handle_event(response)

    # Start response simulation
    asyncio.create_task(simulate_response())

    # Send command with response
    response = await ws_client.send_command(
        "device.get_properties",
        {"serialNumber": "TEST123", "properties": ["battery"]},
        wait_response=True,
        timeout=1.0
    )

    # Verify response was received
    assert response is not None
    assert response["success"] is True
    assert response["result"]["battery"] == 85


@pytest.mark.asyncio
async def test_send_command_with_response_timeout(ws_client):
    """Test sending command times out when no response"""
    mock_ws = AsyncMock()
    ws_client.ws = mock_ws

    # Send command with short timeout (no response will come)
    response = await ws_client.send_command(
        "device.get_properties",
        {"serialNumber": "TEST123"},
        wait_response=True,
        timeout=0.1
    )

    # Should return None on timeout
    assert response is None


@pytest.mark.asyncio
async def test_send_command_without_wait_response(ws_client):
    """Test sending command without waiting for response (backward compatibility)"""
    mock_ws = AsyncMock()
    ws_client.ws = mock_ws

    # Send command without waiting
    response = await ws_client.send_command("test.command", {"param": "value"})

    # Should return None
    assert response is None
    mock_ws.send.assert_called_once()


@pytest.mark.asyncio
async def test_handle_result_event_resolves_pending_request(ws_client):
    """Test handling result event resolves pending request"""
    import uuid

    # Create a pending request
    message_id = str(uuid.uuid4())
    future = asyncio.get_event_loop().create_future()
    ws_client._pending_requests[message_id] = future

    # Handle result event
    result_event = {
        "type": "result",
        "messageId": message_id,
        "success": True,
        "result": {"data": "test"}
    }

    await ws_client._handle_event(result_event)

    # Future should be resolved
    assert future.done()
    assert future.result() == result_event


@pytest.mark.asyncio
async def test_handle_result_event_without_pending_request(ws_client):
    """Test handling result event without pending request (should not crash)"""
    result_event = {
        "type": "result",
        "messageId": "unknown-id",
        "success": False,
        "errorCode": "device_not_found"
    }

    # Should not raise exception
    await ws_client._handle_event(result_event)
