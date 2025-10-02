"""WebSocket client for eufy-security-ws"""

import asyncio
import json
import logging
import uuid
from typing import Callable, Optional, Dict, Any
import websockets
from websockets.client import WebSocketClientProtocol

from ..utils.retry import retry_async

logger = logging.getLogger(__name__)


class WebSocketClient:
    """
    WebSocket client for connecting to eufy-security-ws server

    Handles connection, reconnection, command sending, and event receiving
    """

    def __init__(
        self,
        url: str,
        reconnect_delay: float = 5.0,
        heartbeat_interval: float = 30.0,
    ):
        """
        Initialize WebSocket client

        Args:
            url: WebSocket URL (e.g., ws://127.0.0.1:3000/ws)
            reconnect_delay: Delay between reconnection attempts (seconds)
            heartbeat_interval: Interval for sending ping frames (seconds)
        """
        self.url = url
        self.reconnect_delay = reconnect_delay
        self.heartbeat_interval = heartbeat_interval

        self.ws: Optional[WebSocketClientProtocol] = None
        self.event_handlers: Dict[str, Callable] = {}
        self._running = False
        self._reconnect_task: Optional[asyncio.Task] = None

        # Request-response correlation: messageId -> asyncio.Future
        self._pending_requests: Dict[str, asyncio.Future] = {}

    async def connect(self) -> None:
        """Connect to WebSocket server with 3x retry"""
        try:
            await self._connect_with_retry()
        except Exception as e:
            logger.error(f"Failed to connect after retries: {e}")
            raise

    @retry_async(max_attempts=3, delay=2.0, backoff=2.0)
    async def _connect_with_retry(self) -> None:
        """Internal connection method with retry"""
        logger.info(f"Connecting to eufy-security-ws at {self.url}")
        self.ws = await websockets.connect(
            self.url,
            ping_interval=self.heartbeat_interval,
            ping_timeout=self.heartbeat_interval * 2,
        )
        logger.info("✅ WebSocket connected to eufy-security-ws")

        # Send start_listening command to begin receiving events
        message_id = str(uuid.uuid4())
        start_command = {
            "messageId": message_id,
            "command": "start_listening"
        }
        await self.ws.send(json.dumps(start_command))
        logger.info("📡 Sent start_listening command to eufy-security-ws")

    async def disconnect(self) -> None:
        """Disconnect from WebSocket server"""
        self._running = False

        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass

        if self.ws:
            await self.ws.close()
            self.ws = None
            logger.info("WebSocket disconnected")

    async def send_command(
        self, command: str, params: Optional[Dict[str, Any]] = None, wait_response: bool = False, timeout: float = 10.0
    ) -> Optional[Dict[str, Any]]:
        """
        Send command to eufy-security-ws with 3x retry

        Args:
            command: Command name (e.g., "device.start_livestream")
            params: Command parameters
            wait_response: If True, wait for and return the response
            timeout: Timeout in seconds when waiting for response

        Returns:
            Response dict if wait_response=True, otherwise None
        """
        if not self.ws:
            raise ConnectionError("WebSocket not connected")

        if wait_response:
            return await self._send_command_with_response(command, params or {}, timeout)
        else:
            await self._send_command_with_retry(command, params or {})
            return None

    async def _send_command_with_response(
        self, command: str, params: Dict[str, Any], timeout: float
    ) -> Optional[Dict[str, Any]]:
        """Send command and wait for response"""
        message_id = str(uuid.uuid4())
        message = {"messageId": message_id, "command": command, **params}

        # Create a Future to wait for the response
        future = asyncio.get_event_loop().create_future()
        self._pending_requests[message_id] = future

        try:
            # Send the command
            await self.ws.send(json.dumps(message))
            logger.debug(f"Sent command with response: {command} (messageId: {message_id})")

            # Wait for the response with timeout
            response = await asyncio.wait_for(future, timeout=timeout)
            return response

        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for response to command: {command}")
            return None
        finally:
            # Clean up the pending request
            self._pending_requests.pop(message_id, None)

    @retry_async(max_attempts=3, delay=1.0, backoff=2.0)
    async def _send_command_with_retry(
        self, command: str, params: Dict[str, Any]
    ) -> None:
        """Internal send command method with retry"""
        message = {"command": command, **params}
        await self.ws.send(json.dumps(message))
        logger.debug(f"Sent command: {command}")

    def on(self, event_type: str, handler: Callable) -> None:
        """
        Register event handler

        Args:
            event_type: Event type to listen for (e.g., "motion detected")
            handler: Async function to handle event
        """
        self.event_handlers[event_type] = handler
        logger.debug(f"Registered handler for event: {event_type}")

    async def start_listening(self) -> None:
        """Start listening for WebSocket events"""
        self._running = True
        logger.info("🎧 Starting WebSocket listener loop")

        while self._running:
            try:
                if not self.ws:
                    logger.info("WebSocket not connected, attempting connection...")
                    await self.connect()

                logger.info("📡 Listening for WebSocket messages...")
                async for message in self.ws:
                    try:
                        event = json.loads(message)
                        await self._handle_event(event)
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse WebSocket message: {e}")
                    except Exception as e:
                        logger.error(f"Error handling event: {e}", exc_info=True)

            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket connection closed")
                if self._running:
                    await self._reconnect()
            except Exception as e:
                logger.error(f"WebSocket error: {e}", exc_info=True)
                if self._running:
                    await self._reconnect()

    async def _handle_event(self, event: dict) -> None:
        """Handle incoming WebSocket event or response"""
        # Log ALL raw messages to debug event reception
        msg_type = event.get("type", "unknown")
        logger.debug(f"📨 Raw WebSocket message: type={msg_type}")

        # Handle command responses (type: "result")
        if event.get("type") == "result":
            message_id = event.get("messageId")
            if message_id and message_id in self._pending_requests:
                # Resolve the pending request with the response
                future = self._pending_requests[message_id]
                if not future.done():
                    future.set_result(event)
                logger.debug(f"✅ Resolved response for messageId: {message_id}")
            else:
                logger.debug(f"Received result without pending request: {event}")
            return

        # Handle nested event structure from eufy-security-ws
        # Expected format: {"type": "event", "event": {"event": "motion detected", ...}}
        if event.get("type") == "event" and isinstance(event.get("event"), dict):
            inner_event = event["event"]
            event_type = inner_event.get("event")
            # Use the inner event dict for handlers (contains serialNumber, state, etc.)
            event_data = inner_event
        else:
            # Fallback to flat structure for backward compatibility
            event_type = event.get("event")
            event_data = event

        if not event_type:
            logger.debug(f"Received event without type: {event}")
            return

        # Log ALL events to help debug what events we're receiving
        source = event_data.get("source", "unknown")
        serial_number = event_data.get("serialNumber", "N/A")
        logger.info(f"📦 WebSocket Event: type={event_type}, source={source}, serial={serial_number}")

        # Also log the full event data for station connection events
        if event_type in ("connected", "disconnected"):
            logger.info(f"🔍 Station connection event details: {event_data}")

        handler = self.event_handlers.get(event_type)
        if handler:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event_data)
                else:
                    handler(event_data)
            except Exception as e:
                logger.error(
                    f"Error in event handler for {event_type}: {e}", exc_info=True
                )
        else:
            logger.info(f"No handler registered for event: {event_type}")

    async def _reconnect(self) -> None:
        """Reconnect to WebSocket server"""
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None

        logger.info(f"Reconnecting in {self.reconnect_delay}s...")
        await asyncio.sleep(self.reconnect_delay)

        try:
            await self.connect()
        except Exception as e:
            logger.error(f"Reconnection failed: {e}")