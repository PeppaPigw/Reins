---
phase: 06-performance-observability
plan: 02
subsystem: observability
tags: [tracing, correlation, otel, structlog, contextvars]
dependency_graph:
  requires: []
  provides: [otel-tracing, correlation-propagation, trace-context]
  affects: [kernel-events, api-server, orchestrator]
tech_stack:
  added: []
  patterns: [contextvars-propagation, w3c-traceparent, structlog-processor]
key_files:
  created:
    - src/reins/observability/tracing.py
    - src/reins/observability/spans.py
    - src/reins/observability/correlation.py
    - tests/unit/test_tracing.py
    - tests/unit/test_correlation.py
  modified: []
decisions:
  - Used ULID string encoded to hex for W3C traceparent trace_id field
  - Kept Tracer in-memory span collection for testability (no external export yet)
  - correlation_processor is a standalone structlog processor, composable with existing chain
metrics:
  tasks_completed: 2
  tasks_total: 2
  tests_added: 31
  files_created: 5
---

# Phase 6 Plan 02: Distributed Tracing and Correlation Summary

OTel-compatible tracing with W3C traceparent propagation and correlation ID enrichment via contextvars.

## What Was Delivered

**Task 1 — Tracing System** (a4f857a): Span/TraceContext/Tracer classes with W3C traceparent serialization, span context manager, trace_function decorator, and inject/extract helpers for HTTP header propagation. 19 tests.

**Task 2 — Correlation Propagation** (bb41664): CorrelationContext with contextvars propagation, structlog processor for automatic log enrichment, correlated() context manager with nesting support, and enrich_event_envelope() for EventEnvelope integration. 12 tests.

## Deviations from Plan

None — plan executed exactly as written.

## Verification

All 31 tests pass. Both `from reins.observability.tracing import Tracer` and `from reins.observability.correlation import correlated` succeed.

## Self-Check: PASSED
