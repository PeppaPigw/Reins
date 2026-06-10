"""Tests for throttle engine with rate limiting and backpressure."""

from __future__ import annotations

import pytest

from reins.throttle import (
    BackpressureAction,
    QueueEntry,
    RateLimitConfig,
    ThrottleDecision,
    ThrottleEngine,
    ThrottleScope,
    ThrottleStats,
    ThrottleStrategy,
)


@pytest.fixture
def engine() -> ThrottleEngine:
    return ThrottleEngine()


@pytest.fixture
def configured_engine(engine) -> ThrottleEngine:
    engine.register_config(RateLimitConfig(
        name="default", max_rate=10.0, burst_size=5, window_seconds=60.0,
    ))
    return engine


def test_register_config(engine):
    config = engine.register_config(RateLimitConfig(name="test"))
    assert engine.get_config(config.config_id) is not None


def test_get_config_not_found(engine):
    assert engine.get_config("nonexistent") is None


def test_request_allowed(configured_engine):
    decision = configured_engine.request("agent-1")
    assert decision.action == BackpressureAction.ALLOW


def test_request_no_config_allows(engine):
    decision = engine.request("agent-1")
    assert decision.action == BackpressureAction.ALLOW


def test_request_exhausts_burst(configured_engine):
    for _ in range(5):
        configured_engine.request("agent-1")
    decision = configured_engine.request("agent-1")
    assert decision.action in (BackpressureAction.THROTTLE, BackpressureAction.REJECT)


def test_request_tracks_wait_ms(configured_engine):
    for _ in range(5):
        configured_engine.request("agent-1")
    decision = configured_engine.request("agent-1")
    assert decision.wait_ms > 0


def test_request_per_agent_isolation(configured_engine):
    for _ in range(5):
        configured_engine.request("agent-1")
    decision = configured_engine.request("agent-2")
    assert decision.action == BackpressureAction.ALLOW


def test_request_global_scope(engine):
    engine.register_config(RateLimitConfig(
        name="global", scope=ThrottleScope.GLOBAL, burst_size=3,
    ))
    for _ in range(3):
        engine.request("agent-1")
    decision = engine.request("agent-2")
    assert decision.action != BackpressureAction.ALLOW


def test_request_with_resource(configured_engine):
    decision = configured_engine.request("agent-1", resource="/api/data")
    assert decision.action == BackpressureAction.ALLOW


def test_enqueue(engine):
    entry = engine.enqueue("agent-1", priority=5)
    assert entry.agent_id == "agent-1"
    assert engine.get_queue_size() == 1


def test_dequeue_priority_order(engine):
    engine.enqueue("low", priority=1)
    engine.enqueue("high", priority=10)
    engine.enqueue("mid", priority=5)
    entry = engine.dequeue()
    assert entry.agent_id == "high"


def test_dequeue_empty(engine):
    assert engine.dequeue() is None


def test_get_queue_size(engine):
    engine.enqueue("a")
    engine.enqueue("b")
    assert engine.get_queue_size() == 2


def test_get_decisions_all(configured_engine):
    configured_engine.request("a")
    configured_engine.request("b")
    assert len(configured_engine.get_decisions()) == 2


def test_get_decisions_by_agent(configured_engine):
    configured_engine.request("a")
    configured_engine.request("b")
    assert len(configured_engine.get_decisions(agent_id="a")) == 1


def test_get_decisions_by_action(configured_engine):
    configured_engine.request("a")
    decisions = configured_engine.get_decisions(action=BackpressureAction.ALLOW)
    assert len(decisions) == 1


def test_reset_bucket(configured_engine):
    for _ in range(5):
        configured_engine.request("agent-1")
    configured_engine.reset_bucket("agent-1")
    decision = configured_engine.request("agent-1")
    assert decision.action == BackpressureAction.ALLOW


def test_stats_empty():
    eng = ThrottleEngine()
    stats = eng.get_stats()
    assert stats.total_requests == 0
    assert stats.allowed == 0


def test_stats_with_data(configured_engine):
    for _ in range(3):
        configured_engine.request("agent-1")
    stats = configured_engine.get_stats()
    assert stats.total_requests == 3
    assert stats.allowed == 3
    assert "agent-1" in stats.by_agent


def test_stats_tracks_throttled(configured_engine):
    for _ in range(6):
        configured_engine.request("agent-1")
    stats = configured_engine.get_stats()
    assert stats.throttled + stats.rejected >= 1


def test_reason_included(configured_engine):
    decision = configured_engine.request("agent-1")
    assert len(decision.reason) > 0
