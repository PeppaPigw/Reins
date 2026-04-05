from __future__ import annotations

import logging

import structlog
import ulid


def new_trace_id() -> str:
    return str(ulid.new())


def get_logger(name: str) -> structlog.BoundLogger:
    return structlog.get_logger(name)


def configure_logging(level: str = "INFO") -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
    )
