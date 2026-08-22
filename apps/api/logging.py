"""Structured logging setup.

One JSON-ish structured logger for the whole process, configured from settings.
Every request, stage decision, and external-call retry logs through structlog so
the eval harness and console can consume machine-readable events later.
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog + stdlib logging once at process start.

    Inputs: ``level`` — a stdlib level name (``DEBUG``/``INFO``/...).
    Outputs: none; mutates global logging configuration.
    Failure cases: an unknown level name falls back to ``INFO``.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=numeric_level,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.types.FilteringBoundLogger:
    """Return a bound structured logger for ``name``."""
    return structlog.get_logger(name)
