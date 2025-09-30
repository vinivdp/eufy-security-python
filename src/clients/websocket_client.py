"""WebSocket client for eufy-security-ws"""

import asyncio
import json
import logging
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

    async def send_command(self, command: str, params: Optional[Dict[str, Any]] = None) -> None:
        """
        Send command to eufy-security-ws with 3x retry

        Args:
            command: Command name (e.g., "device.start_livestream")
            params: Command parameters
        """
        if not self.ws:
            raise ConnectionError("WebSocket not connected")

        await self._send_command_with_retry(command, params or {})

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
                    logger.info(f"📨 Raw WebSocket message received: {message[:200]}...")
                    try:
                        event = json.loads(message)
                        logger.info(f"📦 Parsed event: {event.get('event', 'unknown')} - {event}")
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
        """Handle incoming WebSocket event"""
        event_type = event.get("event")

        if not event_type:
            logger.debug(f"Received event without type: {event}")
            return

        logger.debug(f"📦 Received event: {event_type}")

        handler = self.event_handlers.get(event_type)
        if handler:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                logger.error(
                    f"Error in event handler for {event_type}: {e}", exc_info=True
                )
        else:
            logger.debug(f"No handler registered for event: {event_type}")

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