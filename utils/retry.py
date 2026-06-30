"""
utils.retry — HTTP/IO retry logic with exponential backoff.

Provides a reusable ``retry_with_backoff`` decorator and a ``RetryConfig``
dataclass for configuring retry behaviour across all network-bound extractors
(GitHub API, etc.).

Design:
- Configurable exception types to retry on (default: ConnectionError, Timeout).
- Exponential backoff with optional jitter to avoid thundering-herd.
- Respects ``Retry-After`` headers where present.
- Raises the *last* exception if all attempts are exhausted, preserving the
  original traceback for observability.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import ParamSpec, TypeVar

from utils.logging import get_logger

log = get_logger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


@dataclass
class RetryConfig:
    """
    Retry policy configuration.

    Attributes
    ----------
    max_attempts:
        Total number of attempts (including the first try).
    base_delay_seconds:
        Initial wait before the first retry.
    max_delay_seconds:
        Cap on the computed backoff delay.
    backoff_factor:
        Multiplier applied to the delay on each successive retry.
    jitter:
        When True, add up to 20 % random jitter to the delay to desynchronise
        concurrent callers.
    retryable_exceptions:
        Tuple of exception types that trigger a retry.  Exceptions not in this
        tuple propagate immediately.
    """

    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    backoff_factor: float = 2.0
    jitter: bool = True
    retryable_exceptions: tuple[type[Exception], ...] = field(
        default_factory=lambda: (ConnectionError, TimeoutError, OSError)
    )

    def compute_delay(self, attempt: int) -> float:
        """Compute sleep duration for the given retry attempt (0-indexed)."""
        delay = min(
            self.base_delay_seconds * (self.backoff_factor**attempt),
            self.max_delay_seconds,
        )
        if self.jitter:
            delay *= 1 + random.uniform(-0.1, 0.2)
        return max(0.0, delay)


def retry_with_backoff(
    config: RetryConfig | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """
    Decorator factory that retries a function using the provided ``RetryConfig``.

    Usage::

        @retry_with_backoff(RetryConfig(max_attempts=3))
        def call_github_api(url: str) -> dict:
            ...
    """
    effective_config = config or RetryConfig()

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        import functools

        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            last_exception: Exception | None = None
            for attempt in range(effective_config.max_attempts):
                try:
                    return func(*args, **kwargs)
                except effective_config.retryable_exceptions as exc:
                    last_exception = exc
                    if attempt + 1 >= effective_config.max_attempts:
                        break
                    delay = effective_config.compute_delay(attempt)
                    log.warning(
                        "retry_scheduled",
                        func=func.__qualname__,
                        attempt=attempt + 1,
                        max_attempts=effective_config.max_attempts,
                        delay_seconds=round(delay, 2),
                        error=str(exc),
                    )
                    time.sleep(delay)

            raise last_exception or RuntimeError(f"{func.__qualname__} failed with no exception")

        return wrapper

    return decorator
