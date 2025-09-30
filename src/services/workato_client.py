"""Workato webhook client"""

import asyncio
import logging
from typing import Optional, Dict, Any
import aiohttp

from ..utils.retry import retry_async
from ..models.events import BaseEvent

logger = logging.getLogger(__name__)


class RateLimiter:
    """Simple rate limiter for API calls"""

    def __init__(self, rate_per_second: int):
        """
        Initialize rate limiter

        Args:
            rate_per_second: Maximum requests per second
        """
        self.rate_per_second = rate_per_second
        self.min_interval = 1.0 / rate_per_second
        self.last_call = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Acquire rate limit slot"""
        async with self._lock:
            now = asyncio.get_event_loop().time()
            time_since_last = now - self.last_call

            if time_since_last < self.min_interval:
                await asyncio.sleep(self.min_interval - time_since_last)

            self.last_call = asyncio.get_event_loop().time()


class WorkatoWebhook:
    """
    Workato webhook client with retry and rate limiting

    Sends events to Workato webhook endpoint
    """

    def __init__(
        self,
        webhook_url: str,
        timeout: int = 30,
        rate_limit_per_second: int = 20,
        error_logger: Optional["ErrorLogger"] = None,
    ):
        """
        Initialize Workato webhook client

        Args:
            webhook_url: Workato webhook URL
            timeout: Request timeout in seconds
            rate_limit_per_second: Maximum requests per second
            error_logger: ErrorLogger instance for logging failures
        """
        self.webhook_url = webhook_url
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.rate_limiter = RateLimiter(rate_limit_per_second)
        self.error_logger = error_logger

    @retry_async(max_attempts=3, delay=1.0, backoff=2.0)
    async def send(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send webhook with automatic 3x retry

        Args:
            payload: Webhook payload

        Returns:
            Response JSON

        Raises:
            Exception: If all retries fail
        """
        await self.rate_limiter.acquire()

        logger.info(f"Sending webhook: {payload.get('event', 'unknown')}")

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.post(self.webhook_url, json=payload) as resp:
                resp.raise_for_status()
                result = await resp.json()
                logger.info(f"✅ Webhook sent successfully")
                return result

    async def send_event(self, event: BaseEvent) -> None:
        """
        Send event model to webhook

        Args:
            event: Event model instance
        """
        payload = event.model_dump(mode="json")
        await self.send(payload)

    async def send_with_error_logging(
        self, payload: Dict[str, Any], context: Dict[str, Any]
    ) -> None:
        """
        Send webhook and log to ErrorLogger if all retries fail

        Args:
            payload: Webhook payload
            context: Additional context for error logging
        """
        try:
            await self.send(payload)
        except Exception as e:
            logger.error(f"Failed to send webhook after retries: {e}")

            if self.error_logger:
                await self.error_logger.log_failed_retry(
                    operation="workato_webhook",
                    error=e,
                    context={**context, "payload": payload},
                    retry_count=3,
                )
            raise