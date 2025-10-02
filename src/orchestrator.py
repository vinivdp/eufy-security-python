"""Event orchestrator - coordinates all handlers and services"""

import asyncio
import logging
from typing import Optional

from .clients.websocket_client import WebSocketClient
from .services.workato_client import WorkatoWebhook
from .services.error_logger import ErrorLogger
from .services.device_health_checker import DeviceHealthChecker
from .services.camera_registry import CameraRegistry
from .services.state_timeout_checker import StateTimeoutChecker
from .handlers.motion_handler import MotionAlarmHandler
from .utils.config import AppConfig

logger = logging.getLogger(__name__)


class EventOrchestrator:
    """
    Central coordinator for all event handlers and services

    New architecture:
    - Camera registry loaded from CSV
    - Motion detection with state machine (closed→open, timeout→closed)
    - Polling-based health monitoring (battery + offline)
    - Only listens to motion_detected events
    """

    def __init__(self, config: AppConfig):
        """
        Initialize event orchestrator

        Args:
            config: Application configuration
        """
        self.config = config
        self._running = False

        # Initialize core services
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

        # Camera registry
        self.camera_registry = CameraRegistry(registry_path="config/cameras.txt")

        # Health checker (polling-based)
        self.health_checker = DeviceHealthChecker(
            websocket_client=self.websocket_client,
            camera_registry=self.camera_registry,
            workato_webhook=self.workato_webhook,
            error_logger=self.error_logger,
            polling_interval_minutes=config.alerts.offline.polling_interval_minutes,
            failure_threshold=config.alerts.offline.failure_threshold,
            battery_threshold_percent=config.alerts.offline.battery_threshold_percent,
            battery_cooldown_hours=config.alerts.battery.cooldown_hours,
        )

        # Initialize motion handler
        logger.info("Initializing motion handler...")

        self.motion_handler = MotionAlarmHandler(
            camera_registry=self.camera_registry,
            workato_webhook=self.workato_webhook,
            error_logger=self.error_logger,
        )

        # State timeout checker (auto-close after 1hr)
        self.state_timeout_checker = StateTimeoutChecker(
            camera_registry=self.camera_registry,
            workato_webhook=self.workato_webhook,
            error_logger=self.error_logger,
            motion_handler=self.motion_handler,
            timeout_minutes=config.motion.state_timeout_minutes,
            check_interval_seconds=60,
        )

        logger.info("✅ All services and handlers initialized")

    async def start(self) -> None:
        """Start the orchestrator and all services"""
        if self._running:
            logger.warning("Orchestrator already running")
            return

        self._running = True
        logger.info("🚀 Starting Eufy Security Integration")

        # Load camera registry
        try:
            await self.camera_registry.load()
            cameras_count = len(self.camera_registry.cameras)
            logger.info(f"📋 Loaded {cameras_count} cameras from registry")
        except Exception as e:
            logger.error(f"Failed to load camera registry: {e}")
            raise

        # Register event handlers (ONLY motion_detected)
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

        # Start polling services
        await self.health_checker.start()
        await self.state_timeout_checker.start()

        logger.info("✅ Orchestrator started successfully")

    async def stop(self) -> None:
        """Stop the orchestrator and cleanup"""
        if not self._running:
            return

        self._running = False
        logger.info("🛑 Stopping Eufy Security Integration")

        # Stop background services
        await self.health_checker.stop()
        await self.state_timeout_checker.stop()

        # Disconnect WebSocket
        await self.websocket_client.disconnect()

        logger.info("✅ Orchestrator stopped")

    def _register_event_handlers(self) -> None:
        """Register event handlers with WebSocket client"""
        logger.info("Registering event handlers...")

        # ONLY listen to motion detected events
        self.websocket_client.on("motion detected", self.motion_handler.on_motion_detected)

        logger.info("✅ Event handler registered (motion_detected only)")

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
        cameras_count = len(self.camera_registry.cameras)
        open_cameras = len([c for c in self.camera_registry.cameras.values() if c.state == "open"])
        offline_cameras = len(self.health_checker.offline_devices_timestamps)

        return {
            "running": self._running,
            "websocket_connected": self.websocket_client.ws is not None,
            "total_cameras": cameras_count,
            "open_cameras": open_cameras,
            "offline_cameras": offline_cameras,
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
            else:
                logger.debug(f"Ignored event type: {event_type}")
        except Exception as e:
            logger.error(f"Error routing event {event_type}: {e}", exc_info=True)
            await self.error_logger.log_failed_retry(
                operation=f"route_event_{event_type}",
                error=e,
                context={"event": event},
                retry_count=1,
            )
