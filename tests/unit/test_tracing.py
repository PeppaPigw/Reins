"""Tests for OpenTelemetry-compatible tracing system."""

from __future__ import annotations

import asyncio
import time

import pytest

from reins.observability.spans import (
    extract_trace_context,
    get_tracer,
    init_tracer,
    inject_trace_context,
    span,
    trace_function,
)
from reins.observability.tracing import (
    Span,
    SpanKind,
    SpanStatus,
    TraceContext,
    Tracer,
)


@pytest.fixture(autouse=True)
def _fresh_tracer():
    """Reset global tracer and context before each test."""
    import reins.observability.spans as spans_mod
    from reins.observability.tracing import _current_context

    spans_mod._global_tracer = None
    _current_context.set(None)
    yield


class TestSpan:
    def test_span_creation_has_ids(self):
        s = Span(
            trace_id="trace123",
            span_id="span456",
            parent_span_id=None,
            name="test-span",
        )
        assert s.trace_id == "trace123"
        assert s.span_id == "span456"
        assert s.parent_span_id is None
        assert s.name == "test-span"
        assert s.kind == SpanKind.internal
        assert s.status == SpanStatus.unset
        assert s.start_time_ns > 0

    def test_span_duration_calculated(self):
        s = Span(
            trace_id="t", span_id="s", parent_span_id=None, name="dur"
        )
        assert s.duration_ms() is None
        time.sleep(0.01)
        s.end()
        dur = s.duration_ms()
        assert dur is not None
        assert dur >= 5  # at least 5ms (sleep 10ms with tolerance)

    def test_span_set_attribute(self):
        s = Span(trace_id="t", span_id="s", parent_span_id=None, name="attr")
        s.set_attribute("http.method", "GET")
        s.set_attribute("http.status_code", 200)
        assert s.attributes["http.method"] == "GET"
        assert s.attributes["http.status_code"] == 200

    def test_span_add_event(self):
        s = Span(trace_id="t", span_id="s", parent_span_id=None, name="evt")
        s.add_event("exception", {"message": "oops"})
        assert len(s.events) == 1
        assert s.events[0]["name"] == "exception"
        assert s.events[0]["attributes"]["message"] == "oops"
        assert "timestamp_ns" in s.events[0]

    def test_span_end_sets_status(self):
        s = Span(trace_id="t", span_id="s", parent_span_id=None, name="end")
        assert s.is_recording()
        s.end(SpanStatus.error)
        assert not s.is_recording()
        assert s.status == SpanStatus.error
        assert s.end_time_ns is not None


class TestTraceContext:
    def test_trace_context_to_traceparent_format(self):
        ctx = TraceContext(trace_id="abc123", span_id="def456", trace_flags=1)
        tp = ctx.to_traceparent()
        assert tp.startswith("00-")
        parts = tp.split("-")
        assert len(parts) == 4
        assert parts[0] == "00"
        assert len(parts[1]) == 32
        assert len(parts[2]) == 16
        assert parts[3] == "01"

    def test_trace_context_from_traceparent_parses(self):
        ctx = TraceContext(trace_id="mytest", span_id="myspan", trace_flags=1)
        tp = ctx.to_traceparent()
        parsed = TraceContext.from_traceparent(tp)
        assert parsed is not None
        assert parsed.trace_flags == 1

    def test_trace_context_roundtrip(self):
        ctx = TraceContext(trace_id="roundtrip", span_id="spanrt", trace_flags=1)
        tp = ctx.to_traceparent()
        parsed = TraceContext.from_traceparent(tp)
        assert parsed is not None
        # The hex encoding/decoding should preserve the original values
        assert parsed.trace_id == ctx.trace_id
        assert parsed.span_id == ctx.span_id
        assert parsed.trace_flags == ctx.trace_flags

    def test_from_traceparent_invalid_returns_none(self):
        assert TraceContext.from_traceparent("invalid") is None
        assert TraceContext.from_traceparent("01-abc-def-01") is None


class TestTracer:
    def test_tracer_start_span_inherits_trace_id(self):
        tracer = Tracer()
        parent_ctx = TraceContext(trace_id="parent-trace", span_id="parent-span")
        child = tracer.start_span("child", parent=parent_ctx)
        assert child.trace_id == "parent-trace"
        assert child.parent_span_id == "parent-span"

    def test_tracer_start_span_new_trace_without_parent(self):
        tracer = Tracer()
        s = tracer.start_span("root")
        assert s.trace_id != ""
        assert s.parent_span_id is None

    def test_tracer_collects_spans(self):
        tracer = Tracer()
        tracer.start_span("one")
        tracer.start_span("two")
        spans = tracer.get_collected_spans()
        assert len(spans) == 2
        tracer.clear()
        assert len(tracer.get_collected_spans()) == 0

    def test_tracer_get_current_context(self):
        tracer = Tracer()
        tracer.start_span("ctx-test")
        ctx = tracer.get_current_context()
        assert ctx is not None
        assert ctx.trace_id != ""


class TestSpanContextManager:
    def test_span_context_manager_creates_and_ends(self):
        init_tracer("test")
        with span("my-op") as s:
            assert s.is_recording()
            s.set_attribute("key", "val")
        assert not s.is_recording()
        assert s.status == SpanStatus.ok

    def test_span_context_manager_error_status_on_exception(self):
        init_tracer("test")
        with pytest.raises(ValueError):
            with span("fail-op") as s:
                raise ValueError("boom")
        assert s.status == SpanStatus.error
        assert not s.is_recording()


class TestTraceFunction:
    def test_trace_function_decorator_sync(self):
        tracer = init_tracer("test")

        @trace_function(name="my-func")
        def do_work():
            return 42

        result = do_work()
        assert result == 42
        spans = tracer.get_collected_spans()
        assert any(s.name == "my-func" for s in spans)

    def test_trace_function_decorator_async(self):
        tracer = init_tracer("test")

        @trace_function(name="async-func")
        async def do_async():
            return "done"

        result = asyncio.run(do_async())
        assert result == "done"
        spans = tracer.get_collected_spans()
        assert any(s.name == "async-func" for s in spans)


class TestInjectExtract:
    def test_inject_extract_trace_context(self):
        tracer = init_tracer("test")
        tracer.start_span("inject-test")
        headers: dict[str, str] = {}
        inject_trace_context(headers)
        assert "traceparent" in headers

        extracted = extract_trace_context(headers)
        assert extracted is not None

    def test_extract_empty_headers_returns_none(self):
        assert extract_trace_context({}) is None
