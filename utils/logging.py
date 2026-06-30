"""
utils.logging — Structured logging configuration for CandidateFusion AI.

Uses structlog for machine-readable JSON output in production and
pretty-printed console output in development.  All modules should obtain
a logger via ``get_logger(__name__)`` rather than using the stdlib logging
module directly, so that log configuration is centralised here.

Why structlog?
- Supports both JSON and console renderers with zero code change at call sites.
- Context variables (request ID, candidate ID) propagate automatically.
- Compatible with standard Python logging for third-party library output.
- Async-safe.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import structlog
from structlog.types import EventDict, Processor


def _add_severity_field(
    logger: Any,
    method: str,
    event_dict: EventDict,
) -> EventDict:
    """
    Add a ``severity`` field mirroring ``level`` for GCP / Datadog compatibility.

    Some log aggregation platforms index on ``severity`` rather than ``level``.
    This processor adds both without duplicating human effort at call sites.
    """
    event_dict["severity"] = event_dict.get("level", method).upper()
    return event_dict


def _drop_color_message_key(
    logger: Any,
    method: str,
    event_dict: EventDict,
) -> EventDict:
    """Remove the ``color_message`` key injected by uvicorn's access logger."""
    event_dict.pop("color_message", None)
    return event_dict


def setup_logging(
    log_level: str = "INFO",
    log_format: str = "json",
    log_dir: Path | None = None,
) -> None:
    """
    Configure the global structlog and stdlib logging setup.

    Parameters
    ----------
    log_level:
        Root log level string (e.g. "DEBUG", "INFO", "WARNING").
    log_format:
        "json" for production JSON output; "console" for development.
    log_dir:
        If provided, also write JSON logs to ``{log_dir}/pipeline.jsonl``.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        _add_severity_field,
        _drop_color_message_key,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if log_format == "json":
        renderer: Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    # ── Console / stderr handler ──────────────────────────────────────────
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)

    handlers: list[logging.Handler] = [console_handler]

    # ── Optional file handler ─────────────────────────────────────────────
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_path = log_dir / "pipeline.jsonl"
        file_handler = logging.FileHandler(file_path, encoding="utf-8")
        file_formatter = structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ],
        )
        file_handler.setFormatter(file_formatter)
        file_handler.setLevel(level)
        handlers.append(file_handler)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    for handler in handlers:
        root_logger.addHandler(handler)

    # Silence noisy third-party loggers
    for noisy in ("httpx", "urllib3", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    Return a bound structlog logger for the given module name.

    Usage::

        from utils.logging import get_logger
        log = get_logger(__name__)
        log.info("extraction_complete", source="ats", records=1)
    """
    return structlog.get_logger(name)
