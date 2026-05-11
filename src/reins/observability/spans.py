"""Span creation helpers and context propagation utilities."""

from __future__ import annotations

import functools
import inspect
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, Callable

from reins.observability.tracing import (
    Span,
    SpanKind,
    SpanStatus,
    TraceContext,
    Tracer,
    _current_context,
)

_global_tracer: Tracer | None = None


def init_tracer(service_name: str = "reins") -> Tracer:
    """Initialize and set the global tracer. Returns the tracer instance."""
    global _global_tracer
    _global_tracer = Tracer(service_name=service_name)
    return _global_tracer


def get_tracer() -> Tracer:
    """Return the global tracer, creating a default one if needed."""
    global _global_tracer
    if _global_tracer is None:
        _global_tracer = Tracer()
    return _global_tracer


@contextmanager
def span(
    name: str,
    kind: SpanKind = SpanKind.internal,
    attributes: dict[str, str | int | float | bool] | None = None,
) -> Generator[Span, None, None]:
    """Context manager that creates a span, yields it, and ends it on exit."""
    tracer = get_tracer()
    s = tracer.start_span(name, kind=kind)
    if attributes:
        for key, value in attributes.items():
            s.set_attribute(key, value)
    try:
        yield s
    except Exception:
        s.end(status=SpanStatus.error)
        raise
    else:
        s.end(status=SpanStatus.ok)


def trace_function(
    name: str | None = None, kind: SpanKind = SpanKind.internal
) -> Callable[..., Any]:
    """Decorator that wraps a sync or async function with span creation."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        span_name = name or func.__qualname__

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                tracer = get_tracer()
                s = tracer.start_span(span_name, kind=kind)
                try:
                    result = await func(*args, **kwargs)
                except Exception:
                    s.end(status=SpanStatus.error)
                    raise
                else:
                    s.end(status=SpanStatus.ok)
                    return result

            return async_wrapper
        else:

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                tracer = get_tracer()
                s = tracer.start_span(span_name, kind=kind)
                try:
                    result = func(*args, **kwargs)
                except Exception:
                    s.end(status=SpanStatus.error)
                    raise
                else:
                    s.end(status=SpanStatus.ok)
                    return result

            return sync_wrapper

    return decorator


def inject_trace_context(headers: dict[str, str]) -> dict[str, str]:
    """Add traceparent header to the dict from the current trace context."""
    ctx = _current_context.get()
    if ctx is not None:
        headers["traceparent"] = ctx.to_traceparent()
    return headers


def extract_trace_context(headers: dict[str, str]) -> TraceContext | None:
    """Extract a TraceContext from a traceparent header in the dict."""
    traceparent = headers.get("traceparent")
    if traceparent is None:
        return None
    return TraceContext.from_traceparent(traceparent)
