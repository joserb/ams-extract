"""Structured logging setup using structlog.

JSON renderer is the default per the project plan. A text renderer is available
for interactive use via ``configure_logging(log_format="text")``.
"""

from __future__ import annotations

import logging
import sys
from typing import Literal

import structlog
from structlog.typing import Processor

LogFormat = Literal["json", "text"]
LogLevel = Literal["debug", "info", "warning", "error"]


def configure_logging(
    log_format: LogFormat = "json",
    log_level: LogLevel = "info",
) -> None:
    """Configure structlog and the stdlib logging root.

    Args:
        log_format: ``"json"`` (default) for machine-readable output or
            ``"text"`` for human-readable, colored output.
        log_level: Minimum severity to emit.
    """
    level = getattr(logging, log_level.upper())
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=level,
    )

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if log_format == "json"
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
