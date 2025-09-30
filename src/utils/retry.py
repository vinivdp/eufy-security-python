"""Retry decorator with exponential backoff"""

import asyncio
import logging
from functools import wraps
from typing import Callable, Type, Tuple

logger = logging.getLogger(__name__)


def retry_async(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
):
    """
    Async retry decorator with exponential backoff

    Args:
        max_attempts: Number of retry attempts (default 3)
        delay: Initial delay in seconds (default 1.0)
        backoff: Backoff multiplier (default 2.0 = exponential)
        exceptions: Tuple of exceptions to catch (default all)

    Usage:
        @retry_async(max_attempts=3, delay=1.0, backoff=2.0)
        async def my_function():
            # Your code here
            pass
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_attempts:
                        logger.error(
                            f"{func.__name__} failed after {max_attempts} attempts: {e}",
                            exc_info=True,
                        )
                        raise

                    logger.warning(
                        f"{func.__name__} attempt {attempt}/{max_attempts} failed: {e}. "
                        f"Retrying in {current_delay:.1f}s..."
                    )

                    await asyncio.sleep(current_delay)
                    current_delay *= backoff

            # This should never be reached, but just in case
            if last_exception:
                raise last_exception

        return wrapper
    return decorator