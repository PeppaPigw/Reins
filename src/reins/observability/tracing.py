"""OpenTelemetry-compatible tracing with W3C traceparent propagation."""

from __future__ import annotations

import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import ulid


class SpanStatus(str, Enum):
    """Status of a span following OTel conventions."""

    unset = "unset"
    ok = "ok"
    error = "error"


class SpanKind(str, Enum):
    """Kind of span following OTel conventions."""

    internal = "internal"
    server = "server"
    client = "client"
    producer = "producer"
    consumer = "consumer"


@dataclass
class Span:
    """A single span in a distributed trace."""

    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    kind: SpanKind = SpanKind.internal
    start_time_ns: int = field(default_factory=time.time_ns)
    end_time_ns: int | None = None
    status: SpanStatus = SpanStatus.unset
    attributes: dict[str, str | int | float | bool] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    def duration_ms(self) -> float | None:
        """Return span duration in milliseconds, or None if not ended."""
        if self.end_time_ns is None:
            return None
        return (self.end_time_ns - self.start_time_ns) / 1_000_000

    def is_recording(self) -> bool:
        """Return True if the span has not been ended."""
        return self.end_time_ns is None

    def set_attribute(self, key: str, value: str | int | float | bool) -> None:
        """Set an attribute on the span."""
        self.attributes[key] = value

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        """Add a timestamped event to the span."""
        event: dict[str, Any] = {"name": name, "timestamp_ns": time.time_ns()}
        if attributes:
            event["attributes"] = attributes
        self.events.append(event)

    def end(self, status: SpanStatus = SpanStatus.ok) -> None:
        """End the span with the given status."""
        if self.end_time_ns is None:
            self.end_time_ns = time.time_ns()
            self.status = status


def _generate_span_id() -> str:
    """Generate a 16-character hex span ID."""
    return str(ulid.new()).lower()[:16]


def _trace_id_to_hex(trace_id: str) -> str:
    """Convert a ULID trace_id to a 32-char hex string for W3C traceparent."""
    hex_str = trace_id.encode().hex()
    return hex_str[:32].ljust(32, "0")


def _span_id_to_hex(span_id: str) -> str:
    """Convert a span_id to a 16-char hex string for W3C traceparent."""
    hex_str = span_id.encode().hex()
    return hex_str[:16].ljust(16, "0")


@dataclass(frozen=True)
class TraceContext:
    """Immutable trace context for propagation."""

    trace_id: str
    span_id: str
    trace_flags: int = 1  # sampled

    def to_traceparent(self) -> str:
        """Serialize to W3C traceparent format: 00-{trace_id}-{span_id}-{flags}."""
        tid = _trace_id_to_hex(self.trace_id)
        sid = _span_id_to_hex(self.span_id)
        return f"00-{tid}-{sid}-{self.trace_flags:02x}"

    @classmethod
    def from_traceparent(cls, header: str) -> TraceContext | None:
        """Parse a W3C traceparent header. Returns None if invalid."""
        parts = header.split("-")
        if len(parts) != 4 or parts[0] != "00":
            return None
        try:
            trace_id = bytes.fromhex(parts[1]).decode().rstrip("\x00")
        except (ValueError, UnicodeDecodeError):
            trace_id = parts[1]
        try:
            span_id = bytes.fromhex(parts[2]).decode().rstrip("\x00")
        except (ValueError, UnicodeDecodeError):
            span_id = parts[2]
        try:
            flags = int(parts[3], 16)
        except ValueError:
            flags = 1
        return cls(trace_id=trace_id, span_id=span_id, trace_flags=flags)


_current_context: ContextVar[TraceContext | None] = ContextVar(
    "_current_context", default=None
)


class Tracer:
    """In-process tracer that creates spans and manages trace context."""

    def __init__(self, service_name: str = "reins") -> None:
        self._service_name = service_name
        self._spans: list[Span] = []

    def start_span(
        self,
        name: str,
        kind: SpanKind = SpanKind.internal,
        parent: TraceContext | None = None,
    ) -> Span:
        """Create and start a new span. Inherits trace_id from parent if provided."""
        if parent is None:
            parent = _current_context.get()

        if parent is not None:
            trace_id = parent.trace_id
            parent_span_id: str | None = parent.span_id
        else:
            trace_id = str(ulid.new())
            parent_span_id = None

        span_id = _generate_span_id()
        span = Span(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            name=name,
            kind=kind,
        )
        self._spans.append(span)

        # Update current context
        ctx = TraceContext(trace_id=trace_id, span_id=span_id)
        _current_context.set(ctx)

        return span

    def get_current_context(self) -> TraceContext | None:
        """Return the current trace context from the contextvar."""
        return _current_context.get()

    def get_collected_spans(self) -> list[Span]:
        """Return all collected spans (for testing/export)."""
        return list(self._spans)

    def clear(self) -> None:
        """Clear all collected spans."""
        self._spans.clear()
