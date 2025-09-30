"""Error logging service"""

import logging
import traceback
from collections import deque
from datetime import datetime
from typing import Optional, Dict, Any, TYPE_CHECKING

from ..models.errors import ErrorLog

if TYPE_CHECKING:
    from .workato_client import WorkatoWebhook

logger = logging.getLogger(__name__)


class ErrorLogger:
    """
    Centralized error logging and reporting

    Logs failed operations after retries and sends to Workato
    """

    def __init__(
        self,
        workato_webhook: Optional["WorkatoWebhook"] = None,
        keep_in_memory: int = 100,
        send_to_workato: bool = True,
    ):
        """
        Initialize error logger

        Args:
            workato_webhook: WorkatoWebhook instance
            keep_in_memory: Number of errors to keep in memory
            send_to_workato: Whether to send errors to Workato
        """
        self.workato_webhook = workato_webhook
        self.keep_in_memory = keep_in_memory
        self.send_to_workato = send_to_workato
        self.error_history: deque[ErrorLog] = deque(maxlen=keep_in_memory)

    async def log_failed_retry(
        self,
        operation: str,
        error: Exception,
        context: Dict[str, Any],
        retry_count: int = 3,
    ) -> None:
        """
        Log failed operation after all retries exhausted

        Args:
            operation: Name of failed operation (e.g., "motion_detection")
            error: The exception that occurred
            context: Additional context (device_sn, timestamp, etc.)
            retry_count: Number of retries attempted (default 3)
        """
        error_log = ErrorLog(
            operation=operation,
            error_type=type(error).__name__,
            error_message=str(error),
            retry_count=retry_count,
            context=context,
            traceback=traceback.format_exc(),
        )

        # Store in memory
        self.error_history.append(error_log)

        # Log locally
        logger.error(
            f"❌ Failed after {retry_count} retries: {operation}",
            extra={
                "operation": operation,
                "error_type": error_log.error_type,
                "context": context,
            },
        )

        # Send to Workato (with its own error handling)
        if self.send_to_workato and self.workato_webhook:
            try:
                payload = error_log.to_webhook_payload()
                await self.workato_webhook.send(payload)
                logger.info("Error log sent to Workato")
            except Exception as e:
                # Last resort: only log locally if Workato is unreachable
                logger.critical(f"❌ Failed to send error log to Workato: {e}")

    def get_recent_errors(self, limit: int = 10) -> list[dict]:
        """
        Get recent errors for debugging

        Args:
            limit: Maximum number of errors to return

        Returns:
            List of error log dictionaries
        """
        errors = list(self.error_history)[-limit:]
        return [error.model_dump(mode="json") for error in errors]

    def clear_history(self) -> None:
        """Clear error history"""
        self.error_history.clear()
        logger.info("Error history cleared")