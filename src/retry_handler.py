"""
Retry Handler — Exponential backoff decorator for external API calls.

Usage:
    from src.retry_handler import exponential_backoff

    @exponential_backoff(max_attempts=3, base_delay=1.0, exceptions=(requests.Timeout,))
    def call_razorpay_api(...):
        ...
"""
import logging
import time
from functools import wraps
from typing import Tuple, Type

logger = logging.getLogger(__name__)


def exponential_backoff(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    backoff_factor: float = 2.0,
    max_delay: float = 30.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    reraise: bool = True,
):
    """
    Decorator: retry a function with exponential backoff on transient failures.

    Args:
        max_attempts:   Maximum number of tries (including the first attempt).
        base_delay:     Initial delay in seconds after the first failure.
        backoff_factor: Multiplier applied to delay on each subsequent retry.
        max_delay:      Cap on delay between retries (seconds).
        exceptions:     Tuple of exception types to catch and retry on.
                        Exceptions NOT in this tuple propagate immediately.
        reraise:        If True, re-raises the last exception after exhausting
                        all attempts. If False, returns None.

    Delay schedule (base_delay=1, factor=2):
        Attempt 1  → immediate
        Attempt 2  → 1 s
        Attempt 3  → 2 s
        Attempt 4  → 4 s  (capped at max_delay)

    Example:
        @exponential_backoff(max_attempts=3, base_delay=1.0,
                             exceptions=(requests.Timeout, requests.ConnectionError))
        def call_api():
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = base_delay
            last_exc = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)

                except exceptions as exc:  # type: ignore[misc]
                    last_exc = exc

                    if attempt == max_attempts:
                        logger.error(
                            "[%s] All %d attempts failed. Last error: %s",
                            func.__name__, max_attempts, exc,
                        )
                        break

                    sleep_time = min(delay, max_delay)
                    logger.warning(
                        "[%s] Attempt %d/%d failed (%s). Retrying in %.1f s...",
                        func.__name__, attempt, max_attempts,
                        type(exc).__name__, sleep_time,
                    )
                    time.sleep(sleep_time)
                    delay *= backoff_factor

            if reraise and last_exc is not None:
                raise last_exc
            return None

        return wrapper
    return decorator
