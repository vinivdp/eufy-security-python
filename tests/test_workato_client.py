"""Tests for Workato webhook client"""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from aiohttp import ClientError

from src.services.workato_client import WorkatoWebhook, RateLimiter
from src.models.events import MotionDetectedEvent


@pytest.mark.asyncio
async def test_rate_limiter():
    """Test rate limiter enforces rate limit"""
    limiter = RateLimiter(rate_per_second=10)

    start = asyncio.get_event_loop().time()

    # Acquire 3 slots
    await limiter.acquire()
    await limiter.acquire()
    await limiter.acquire()

    elapsed = asyncio.get_event_loop().time() - start

    # Should take at least 0.2 seconds (3 calls at 10/sec = 0.1s interval each)
    assert elapsed >= 0.2


@pytest.mark.asyncio
async def test_send_webhook_success():
    """Test successful webhook send"""
    webhook = WorkatoWebhook(
        webhook_url="https://test.workato.com/webhook",
        rate_limit_per_second=100
    )

    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = AsyncMock(return_value={"success": True})
        mock_post.return_value.__aenter__.return_value = mock_response

        result = await webhook.send({"event": "test"})

        assert result == {"success": True}
        mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_send_event_model():
    """Test sending event model"""
    from src.models.events import get_brasilia_now

    webhook = WorkatoWebhook(
        webhook_url="https://test.workato.com/webhook",
        rate_limit_per_second=100
    )

    event = MotionDetectedEvent(
        device_sn="T8600P1234567890",
        slack_channel="test-channel",
        state="open",
        latest_activity=get_brasilia_now()
    )

    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = AsyncMock(return_value={"success": True})
        mock_post.return_value.__aenter__.return_value = mock_response

        await webhook.send_event(event)

        # Verify the payload was serialized correctly
        call_args = mock_post.call_args
        payload = call_args.kwargs["json"]

        assert payload["event"] == "motion_detected"
        assert payload["device_sn"] == "T8600P1234567890"


@pytest.mark.asyncio
async def test_send_webhook_with_retry():
    """Test webhook retries on failure"""
    webhook = WorkatoWebhook(
        webhook_url="https://test.workato.com/webhook",
        rate_limit_per_second=100
    )

    with patch("aiohttp.ClientSession.post") as mock_post:
        # First 2 calls fail, 3rd succeeds
        mock_response_fail = AsyncMock()
        mock_response_fail.raise_for_status = MagicMock(
            side_effect=ClientError("Connection failed")
        )

        mock_response_success = AsyncMock()
        mock_response_success.raise_for_status = MagicMock()
        mock_response_success.json = AsyncMock(return_value={"success": True})

        mock_post.return_value.__aenter__.side_effect = [
            mock_response_fail,
            mock_response_fail,
            mock_response_success,
        ]

        result = await webhook.send({"event": "test"})

        assert result == {"success": True}
        assert mock_post.call_count == 3


@pytest.mark.asyncio
async def test_send_webhook_all_retries_fail():
    """Test webhook fails after all retries"""
    webhook = WorkatoWebhook(
        webhook_url="https://test.workato.com/webhook",
        rate_limit_per_second=100
    )

    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock(
            side_effect=ClientError("Connection failed")
        )
        mock_post.return_value.__aenter__.return_value = mock_response

        with pytest.raises(ClientError):
            await webhook.send({"event": "test"})

        assert mock_post.call_count == 3  # Should retry 3 times
