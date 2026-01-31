"""
Utility functions: retry logic, rate limiting, and helpers.
"""

import asyncio
import functools
import time
from collections import deque
from datetime import datetime
from typing import Any, Callable, TypeVar, Optional
import random

from .logger import get_logger

logger = get_logger("polymarket.utils")

T = TypeVar("T")


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    exceptions: tuple = (Exception,),
):
    """
    Decorator for retrying functions with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay between retries (seconds)
        max_delay: Maximum delay between retries (seconds)
        exponential_base: Base for exponential backoff
        jitter: Add random jitter to delay
        exceptions: Tuple of exceptions to catch and retry

    Usage:
        @retry_with_backoff(max_retries=3)
        def flaky_api_call():
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_retries:
                        logger.error(
                            f"{func.__name__} failed after {max_retries + 1} attempts: {e}"
                        )
                        raise

                    # Calculate delay with exponential backoff
                    delay = min(
                        base_delay * (exponential_base ** attempt),
                        max_delay
                    )

                    # Add jitter
                    if jitter:
                        delay = delay * (0.5 + random.random())

                    logger.warning(
                        f"{func.__name__} attempt {attempt + 1} failed: {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)

            raise last_exception

        return wrapper
    return decorator


def async_retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    exceptions: tuple = (Exception,),
):
    """Async version of retry_with_backoff."""
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_retries:
                        logger.error(
                            f"{func.__name__} failed after {max_retries + 1} attempts: {e}"
                        )
                        raise

                    delay = min(
                        base_delay * (exponential_base ** attempt),
                        max_delay
                    )
                    if jitter:
                        delay = delay * (0.5 + random.random())

                    logger.warning(
                        f"{func.__name__} attempt {attempt + 1} failed: {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)

            raise last_exception

        return wrapper
    return decorator


class RateLimiter:
    """
    Token bucket rate limiter for API calls.

    Args:
        calls_per_minute: Maximum calls allowed per minute
        burst_size: Maximum burst size (defaults to calls_per_minute)
    """

    def __init__(self, calls_per_minute: int, burst_size: Optional[int] = None):
        self.rate = calls_per_minute / 60.0  # tokens per second
        self.capacity = burst_size or calls_per_minute
        self.tokens = self.capacity
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock() if asyncio.get_event_loop().is_running() else None

    def _refill(self):
        """Refill tokens based on time passed."""
        now = time.monotonic()
        elapsed = now - self.last_update
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_update = now

    def acquire(self, tokens: int = 1) -> float:
        """
        Acquire tokens, blocking if necessary.
        Returns wait time in seconds (0 if no wait needed).
        """
        self._refill()

        if self.tokens >= tokens:
            self.tokens -= tokens
            return 0.0

        # Calculate wait time
        needed = tokens - self.tokens
        wait_time = needed / self.rate

        time.sleep(wait_time)
        self._refill()
        self.tokens -= tokens
        return wait_time

    async def acquire_async(self, tokens: int = 1) -> float:
        """Async version of acquire."""
        async with self._lock or asyncio.Lock():
            self._refill()

            if self.tokens >= tokens:
                self.tokens -= tokens
                return 0.0

            needed = tokens - self.tokens
            wait_time = needed / self.rate

            await asyncio.sleep(wait_time)
            self._refill()
            self.tokens -= tokens
            return wait_time

    def can_acquire(self, tokens: int = 1) -> bool:
        """Check if tokens can be acquired without blocking."""
        self._refill()
        return self.tokens >= tokens


class SlidingWindowRateLimiter:
    """
    Sliding window rate limiter - more precise than token bucket.
    Tracks actual timestamps of calls within the window.
    """

    def __init__(self, max_calls: int, window_seconds: float = 60.0):
        self.max_calls = max_calls
        self.window = window_seconds
        self.calls: deque[float] = deque()

    def _cleanup(self):
        """Remove calls outside the window."""
        cutoff = time.monotonic() - self.window
        while self.calls and self.calls[0] < cutoff:
            self.calls.popleft()

    def acquire(self) -> float:
        """
        Acquire a slot, blocking if at capacity.
        Returns wait time in seconds.
        """
        self._cleanup()

        if len(self.calls) < self.max_calls:
            self.calls.append(time.monotonic())
            return 0.0

        # Calculate when the oldest call will expire
        wait_time = self.calls[0] + self.window - time.monotonic()
        if wait_time > 0:
            time.sleep(wait_time)
            self._cleanup()

        self.calls.append(time.monotonic())
        return max(0, wait_time)

    def can_acquire(self) -> bool:
        """Check if a call can be made without waiting."""
        self._cleanup()
        return len(self.calls) < self.max_calls


def chunk_list(lst: list, chunk_size: int) -> list[list]:
    """Split a list into chunks of specified size."""
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Safe division that returns default on zero denominator."""
    if denominator == 0:
        return default
    return numerator / denominator


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp a value between min and max."""
    return max(min_val, min(max_val, value))


def format_currency(amount: float, symbol: str = "$") -> str:
    """Format amount as currency."""
    if amount >= 0:
        return f"{symbol}{amount:.2f}"
    return f"-{symbol}{abs(amount):.2f}"


def format_percentage(value: float, decimals: int = 1) -> str:
    """Format value as percentage."""
    sign = "+" if value > 0 else ""
    return f"{sign}{value * 100:.{decimals}f}%"


def truncate_string(s: str, max_length: int, suffix: str = "...") -> str:
    """Truncate string to max length with suffix."""
    if len(s) <= max_length:
        return s
    return s[:max_length - len(suffix)] + suffix


def parse_iso_datetime(dt_string: str) -> Optional[datetime]:
    """Parse ISO format datetime string."""
    if not dt_string:
        return None
    try:
        # Handle various ISO formats
        dt_string = dt_string.replace("Z", "+00:00")
        return datetime.fromisoformat(dt_string)
    except (ValueError, TypeError):
        return None


def calculate_time_until(dt: datetime) -> dict:
    """Calculate time components until a datetime."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=None)

    now = datetime.utcnow()
    delta = dt - now

    total_seconds = delta.total_seconds()
    if total_seconds < 0:
        return {"expired": True, "total_seconds": total_seconds}

    days = int(total_seconds // 86400)
    hours = int((total_seconds % 86400) // 3600)
    minutes = int((total_seconds % 3600) // 60)

    return {
        "expired": False,
        "days": days,
        "hours": hours,
        "minutes": minutes,
        "total_seconds": total_seconds,
        "total_hours": total_seconds / 3600,
        "total_days": total_seconds / 86400,
    }


class Timer:
    """Context manager for timing code blocks."""

    def __init__(self, name: str = ""):
        self.name = name
        self.start = 0.0
        self.elapsed = 0.0

    def __enter__(self):
        self.start = time.monotonic()
        return self

    def __exit__(self, *args):
        self.elapsed = time.monotonic() - self.start
        if self.name:
            logger.debug(f"{self.name} took {self.elapsed:.3f}s")


def memoize_with_ttl(ttl_seconds: float):
    """
    Memoization decorator with time-to-live.

    Args:
        ttl_seconds: How long to cache results
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        cache: dict[str, tuple[float, Any]] = {}

        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            # Create cache key from args
            key = str((args, sorted(kwargs.items())))
            now = time.monotonic()

            if key in cache:
                timestamp, value = cache[key]
                if now - timestamp < ttl_seconds:
                    return value

            result = func(*args, **kwargs)
            cache[key] = (now, result)

            # Cleanup old entries
            expired = [k for k, (t, _) in cache.items() if now - t >= ttl_seconds]
            for k in expired:
                del cache[k]

            return result

        wrapper.clear_cache = lambda: cache.clear()
        return wrapper

    return decorator
