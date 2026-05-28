"""Regression tests for the structlog setup."""

from __future__ import annotations

import io
import sys

import structlog

from ams_extract.logging_setup import configure_logging


def test_logger_survives_sys_stderr_swap() -> None:
    """Re-binding ``sys.stderr`` between emits must not raise.

    pytest swaps ``sys.stderr`` between tests and closes prior capture
    buffers; a logger that captured an earlier stderr by reference would
    blow up on the next emit. The lazy stderr factory avoids that.
    """
    original_stderr = sys.stderr
    try:
        configure_logging(log_format="json", log_level="info")
        log = structlog.get_logger("ams_extract.tests")

        first_buffer = io.StringIO()
        sys.stderr = first_buffer
        log.info("first")
        first_output = first_buffer.getvalue()
        first_buffer.close()

        second_buffer = io.StringIO()
        sys.stderr = second_buffer
        log.info("second")

        assert "first" in first_output
        assert "second" in second_buffer.getvalue()
    finally:
        sys.stderr = original_stderr
