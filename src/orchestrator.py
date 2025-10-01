"""Event orchestrator - coordinates all handlers and services"""

import asyncio
import logging
from typing import Optional

from .clients.websocket_client import WebSocketClient
from .services.workato_client import WorkatoWebhook
from .services.error_logger import ErrorLogger
from .services.device_health_checker import DeviceHealthChecker
from .handlers.motion_handler import MotionAlarmHandler
from .handlers.offline_handler import OfflineAlarmHandler
from .handlers.battery_handler import BatteryAlarmHandler
from .utils.config import AppConfig

logger = logging.getLogger(__name__)


class EventOrchestrator:
    """
    Central coordinator for all event handlers and services

    Initializes components and routes events to appropriate handlers
    """

    def __init__(self, config: AppConfig):
        """
        Initialize event orchestrator

        Args:
            config: Application configuration
        """
        self.config = config
        self._running = False

        # Initialize services
        logger.info("Initializing services...")

        self.workato_webhook = WorkatoWebhook(
            webhook_url=config.workato.webhook_url,
            timeout=config.workato.timeout_seconds,
            rate_limit_per_second=config.workato.rate_limit_per_second,
        )

        self.error_logger = ErrorLogger(
            workato_webhook=self.workato_webhook,
            keep_in_memory=config.error_logging.keep_in_memory,
            send_to_workato=config.error_logging.send_to_workato,
        )

        # Set error logger on workato client
        self.workato_webhook.error_logger = self.error_logger

        self.websocket_client = WebSocketClient(
            url=config.eufy.websocket_url,
            reconnect_delay=config.eufy.reconnect_delay,
            heartbeat_interval=config.eufy.heartbeat_interval,
        )

        self.health_checker = DeviceHealthChecker(
            websocket_client=self.websocket_client,
            health_check_timeout=10,
        )

        # Initialize handlers
        logger.info("Initializing event handlers...")

        self.motion_handler = MotionAlarmHandler(
            workato_webhook=self.workato_webhook,
            error_logger=self.error_logger,
            websocket_client=self.websocket_client,
            motion_timeout_seconds=config.recording.motion_timeout_seconds,
            max_duration_seconds=config.recording.max_duration_seconds,
            snooze_duration_seconds=config.recording.snooze_duration_seconds,
        )

        self.offline_handler = OfflineAlarmHandler(
            workato_webhook=self.workato_webhook,
            error_logger=self.error_logger,
            health_checker=self.health_checker,
            debounce_seconds=config.alerts.offline.debounce_seconds,
        )

        self.battery_handler = BatteryAlarmHandler(
            workato_webhook=self.workato_webhook,
            error_logger=self.error_logger,
            cooldown_hours=config.alerts.battery.cooldown_hours,
        )

        logger.info("✅ All services and handlers initialized")

    async def start(self) -> None:
        """Start the orchestrator and all services"""
        if self._running:
            logger.warning("Orchestrator already running")
            return

        self._running = True
        logger.info("🚀 Starting Eufy Security Integration")

        # Register event handlers
        self._register_event_handlers()

        # Start WebSocket client
        try:
            await self.websocket_client.connect()
        except Exception as e:
            logger.error(f"Failed to connect to eufy-security-ws: {e}")
            await self.error_logger.log_failed_retry(
                operation="websocket_connect",
                error=e,
                context={},
                retry_count=3,
            )
            raise

        # Start background tasks
        asyncio.create_task(self._run_websocket_listener())

        logger.info("✅ Orchestrator started successfully")

    async def stop(self) -> None:
        """Stop the orchestrator and cleanup"""
        if not self._running:
            return

        self._running = False
        logger.info("🛑 Stopping Eufy Security Integration")

        # Disconnect WebSocket
        await self.websocket_client.disconnect()

        logger.info("✅ Orchestrator stopped")

    def _register_event_handlers(self) -> None:
        """Register event handlers with WebSocket client"""
        logger.info("Registering event handlers...")

        # Motion events
        self.websocket_client.on("motion detected", self.motion_handler.on_motion_detected)

        # Offline events (legacy disconnect-based)
        self.websocket_client.on("disconnected", self.offline_handler.on_disconnect)
        self.websocket_client.on("device removed", self.offline_handler.on_disconnect)
        self.websocket_client.on("connected", self.offline_handler.on_reconnect)
        self.websocket_client.on("device added", self.offline_handler.on_reconnect)

        # Property changed events (for DeviceState monitoring)
        self.websocket_client.on("property changed", self.offline_handler.on_device_state_changed)

        # Battery events
        self.websocket_client.on("low battery", self.battery_handler.on_low_battery)

        logger.info("✅ Event handlers registered")

    async def _run_websocket_listener(self) -> None:
        """Run WebSocket listener loop"""
        try:
            await self.websocket_client.start_listening()
        except Exception as e:
            logger.error(f"WebSocket listener error: {e}", exc_info=True)
            await self.error_logger.log_failed_retry(
                operation="websocket_listener",
                error=e,
                context={},
                retry_count=1,
            )

    def get_status(self) -> dict:
        """Get orchestrator status"""
        return {
            "running": self._running,
            "websocket_connected": self.websocket_client.ws is not None,
            "offline_devices": len(self.offline_handler.offline_since),
        }

    async def _route_event(self, event: dict) -> None:
        """
        Route event to appropriate handler (for testing)

        Args:
            event: Event dict from WebSocket
        """
        event_type = event.get("event", "").lower()

        try:
            if event_type == "motion_detected" or event_type == "motion detected":
                await self.motion_handler.on_motion_detected(event)
            elif event_type in ["device.disconnect", "disconnected", "device removed"]:
                await self.offline_handler.on_disconnect(event)
            elif event_type in ["device.connect", "connected", "device added"]:
                await self.offline_handler.on_reconnect(event)
            elif event_type == "low_battery" or event_type == "low battery":
                await self.battery_handler.on_low_battery(event)
            else:
                logger.debug(f"Unhandled event type: {event_type}")
        except Exception as e:
            logger.error(f"Error routing event {event_type}: {e}", exc_info=True)
            await self.error_logger.log_failed_retry(
                operation=f"route_event_{event_type}",
                error=e,
                context={"event": event},
                retry_count=1,
            )