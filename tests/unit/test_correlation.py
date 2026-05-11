"""Tests for correlation ID propagation."""

from __future__ import annotations

import json

import pytest
import structlog

from reins.observability.correlation import (
    CorrelationContext,
    _correlation_ctx,
    configure_correlated_logging,
    correlated,
    correlation_processor,
    enrich_event_envelope,
    get_correlation,
    new_correlation,
    set_correlation,
)


@pytest.fixture(autouse=True)
def _reset_correlation():
    """Reset correlation context before each test."""
    _correlation_ctx.set(None)
    yield
    _correlation_ctx.set(None)


class TestCorrelationContext:
    def test_new_correlation_generates_ids(self):
        ctx = new_correlation()
        assert ctx.trace_id != ""
        assert ctx.span_id != ""
        assert len(ctx.span_id) == 16
        assert ctx.run_id is None
        assert ctx.task_id is None

    def test_correlation_context_fields(self):
        ctx = CorrelationContext(
            trace_id="t1",
            span_id="s1",
            run_id="run-1",
            task_id="task-1",
            request_id="req-1",
        )
        assert ctx.trace_id == "t1"
        assert ctx.span_id == "s1"
        assert ctx.run_id == "run-1"
        assert ctx.task_id == "task-1"
        assert ctx.request_id == "req-1"

    def test_set_and_get_correlation(self):
        assert get_correlation() is None
        ctx = new_correlation(run_id="r1")
        set_correlation(ctx)
        assert get_correlation() is ctx
        assert get_correlation().run_id == "r1"


class TestCorrelationProcessor:
    def test_correlation_processor_enriches_log(self):
        ctx = CorrelationContext(
            trace_id="trace-abc",
            span_id="span-def",
            run_id="run-123",
            task_id="task-456",
        )
        set_correlation(ctx)
        event_dict: dict = {"event": "test message"}
        result = correlation_processor(None, "info", event_dict)
        assert result["trace_id"] == "trace-abc"
        assert result["span_id"] == "span-def"
        assert result["run_id"] == "run-123"
        assert result["task_id"] == "task-456"

    def test_correlation_processor_no_context_is_noop(self):
        event_dict: dict = {"event": "test message"}
        result = correlation_processor(None, "info", event_dict)
        assert "trace_id" not in result
        assert "span_id" not in result


class TestCorrelatedContextManager:
    def test_correlated_context_manager_sets_context(self):
        assert get_correlation() is None
        with correlated(run_id="run-x", task_id="task-y") as ctx:
            assert get_correlation() is ctx
            assert ctx.run_id == "run-x"
            assert ctx.task_id == "task-y"
        assert get_correlation() is None

    def test_correlated_context_manager_restores_previous(self):
        outer = new_correlation(run_id="outer")
        set_correlation(outer)
        with correlated(run_id="inner") as inner_ctx:
            assert get_correlation().run_id == "inner"
        assert get_correlation() is outer
        assert get_correlation().run_id == "outer"

    def test_multiple_nested_correlations(self):
        with correlated(run_id="level-1") as c1:
            assert get_correlation().run_id == "level-1"
            with correlated(run_id="level-2") as c2:
                assert get_correlation().run_id == "level-2"
            assert get_correlation().run_id == "level-1"
        assert get_correlation() is None


class TestEnrichEventEnvelope:
    def test_enrich_event_envelope_adds_trace_id(self):
        ctx = CorrelationContext(
            trace_id="t-enrich", span_id="s-enrich", task_id="task-e"
        )
        kwargs: dict = {"run_id": "run-1", "type": "test.event"}
        result = enrich_event_envelope(kwargs, correlation=ctx)
        assert result["trace_id"] == "t-enrich"
        assert result["correlation_id"] == "t-enrich"
        assert result["task_id"] == "task-e"

    def test_enrich_event_envelope_uses_current_context(self):
        ctx = new_correlation(run_id="auto-run", task_id="auto-task")
        set_correlation(ctx)
        kwargs: dict = {"run_id": "run-1"}
        result = enrich_event_envelope(kwargs)
        assert result["trace_id"] == ctx.trace_id
        assert result["correlation_id"] == ctx.trace_id

    def test_enrich_event_envelope_no_context_noop(self):
        kwargs: dict = {"run_id": "run-1", "type": "test"}
        result = enrich_event_envelope(kwargs)
        assert "correlation_id" not in result


class TestConfigureCorrelatedLogging:
    def test_configure_correlated_logging_works(self):
        configure_correlated_logging("DEBUG")
        ctx = CorrelationContext(
            trace_id="log-trace", span_id="log-span", run_id="log-run"
        )
        set_correlation(ctx)
        # Verify structlog is configured and can produce output
        logger = structlog.get_logger("test")
        # Just verify it doesn't raise
        assert logger is not None
