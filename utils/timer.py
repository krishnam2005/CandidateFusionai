"""
utils.timer — Execution timing utilities.

Provides a ``timed`` context manager that logs start/end with elapsed
milliseconds via structlog, and a ``@timed_function`` decorator for
convenient function-level instrumentation.
"""

from __future__ import annotations

import functools
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any, ParamSpec, TypeVar

from utils.logging import get_logger

log = get_logger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


@contextmanager
def timed(operation: str, **extra: Any) -> Generator[None, None, None]:
    """
    Context manager that logs elapsed time for a named operation.

    Usage::

        with timed("github_extraction", username="octocat"):
            result = github_extractor.extract(url)

    Logs::

        {"event": "operation_start", "operation": "github_extraction", "username": "octocat"}
        {"event": "operation_complete", "operation": "github_extraction",
         "elapsed_ms": 342.7, "username": "octocat"}
    """
    log.debug("operation_start", operation=operation, **extra)
    start = time.perf_counter()
    try:
        yield
    except Exception:
        elapsed_ms = (time.perf_counter() - start) * 1000
        log.error("operation_failed", operation=operation, elapsed_ms=round(elapsed_ms, 2), **extra)
        raise
    else:
        elapsed_ms = (time.perf_counter() - start) * 1000
        log.info(
            "operation_complete",
            operation=operation,
            elapsed_ms=round(elapsed_ms, 2),
            **extra,
        )


def timed_function(operation_name: str | None = None) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """
    Decorator that wraps a function with the ``timed`` context manager.

    Parameters
    ----------
    operation_name:
        Override for the logged operation name.  Defaults to the function's
        qualified name.

    Usage::

        @timed_function("csv_extraction")
        def extract(self, path: Path) -> ExtractedCandidate:
            ...
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        name = operation_name or func.__qualname__

        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            with timed(name):
                return func(*args, **kwargs)

        return wrapper

    return decorator
