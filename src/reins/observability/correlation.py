"""Correlation ID propagation across layers via contextvars."""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

import structlog
import ulid

from reins.observability.tracing import TraceContext, _current_context


@dataclass
class CorrelationContext:
    """Correlation context linking traces, spans, runs, and tasks."""

    trace_id: str
    span_id: str
    run_id: str | None = None
    task_id: str | None = None
    request_id: str | None = None


_correlation_ctx: ContextVar[CorrelationContext | None] = ContextVar(
    "_correlation_ctx", default=None
)


def set_correlation(ctx: CorrelationContext) -> None:
    """Set the current correlation context."""
    _correlation_ctx.set(ctx)


def get_correlation() -> CorrelationContext | None:
    """Get the current correlation context."""
    return _correlation_ctx.get()


def new_correlation(
    run_id: str | None = None, task_id: str | None = None
) -> CorrelationContext:
    """Create a new correlation context with fresh trace_id and span_id."""
    return CorrelationContext(
        trace_id=str(ulid.new()),
        span_id=str(ulid.new()).lower()[:16],
        run_id=run_id,
        task_id=task_id,
    )


def correlation_processor(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Structlog processor that enriches log entries with correlation context."""
    ctx = _correlation_ctx.get()
    if ctx is not None:
        event_dict["trace_id"] = ctx.trace_id
        event_dict["span_id"] = ctx.span_id
        if ctx.run_id is not None:
            event_dict["run_id"] = ctx.run_id
        if ctx.task_id is not None:
            event_dict["task_id"] = ctx.task_id
        if ctx.request_id is not None:
            event_dict["request_id"] = ctx.request_id
    return event_dict


def configure_correlated_logging(level: str = "INFO") -> None:
    """Configure structlog with correlation_processor in the processor chain."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    structlog.configure(
        processors=[
            correlation_processor,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
    )


@contextmanager
def correlated(
    run_id: str | None = None, task_id: str | None = None
) -> Generator[CorrelationContext, None, None]:
    """Context manager that sets correlation context for the block."""
    previous = _correlation_ctx.get()
    ctx = new_correlation(run_id=run_id, task_id=task_id)
    _correlation_ctx.set(ctx)
    try:
        yield ctx
    finally:
        _correlation_ctx.set(previous)


def enrich_event_envelope(
    envelope_kwargs: dict[str, Any],
    correlation: CorrelationContext | None = None,
) -> dict[str, Any]:
    """Add trace_id and causation context to event envelope kwargs.

    Uses the current correlation context if none is provided explicitly.
    """
    if correlation is None:
        correlation = _correlation_ctx.get()
    if correlation is not None:
        envelope_kwargs["trace_id"] = correlation.trace_id
        envelope_kwargs["correlation_id"] = correlation.trace_id
        if correlation.task_id is not None:
            envelope_kwargs.setdefault("task_id", correlation.task_id)
    return envelope_kwargs
