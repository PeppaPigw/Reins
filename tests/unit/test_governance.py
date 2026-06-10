"""Tests for cost governance engine."""

from __future__ import annotations

import pytest

from reins.governance import (
    BudgetAlertKind,
    BudgetPeriod,
    CircuitBreakerStatus,
    CostGovernanceEngine,
    ThrottleAction,
)


@pytest.fixture
def engine() -> CostGovernanceEngine:
    return CostGovernanceEngine(circuit_breaker_threshold=3, circuit_breaker_cooldown=60)


def test_set_and_get_budget(engine):
    budget = engine.set_budget("agent-1", limit=10.0, period=BudgetPeriod.DAILY)
    assert budget.agent_id == "agent-1"
    assert budget.limit == 10.0
    retrieved = engine.get_budget("agent-1")
    assert retrieved is not None
    assert retrieved.limit == 10.0


def test_get_budget_nonexistent(engine):
    assert engine.get_budget("nonexistent") is None


def test_record_spend(engine):
    engine.set_budget("agent-1", limit=10.0)
    record = engine.record_spend("agent-1", 0.5, model_id="claude-sonnet")
    assert record.amount == 0.5
    assert record.model_id == "claude-sonnet"


def test_get_spend(engine):
    engine.set_budget("agent-1", limit=10.0)
    engine.record_spend("agent-1", 1.0)
    engine.record_spend("agent-1", 2.0)
    assert engine.get_spend("agent-1") == 3.0


def test_get_utilization(engine):
    engine.set_budget("agent-1", limit=10.0)
    engine.record_spend("agent-1", 5.0)
    assert engine.get_utilization("agent-1") == pytest.approx(0.5)


def test_utilization_no_budget(engine):
    assert engine.get_utilization("agent-1") == 0.0


def test_evaluate_request_allow(engine):
    engine.set_budget("agent-1", limit=10.0)
    policy = engine.evaluate_request("agent-1", estimated_cost=1.0)
    assert policy.action == ThrottleAction.ALLOW


def test_evaluate_request_deny_over_budget(engine):
    engine.set_budget("agent-1", limit=1.0)
    engine.record_spend("agent-1", 0.9)
    policy = engine.evaluate_request("agent-1", estimated_cost=0.2)
    assert policy.action == ThrottleAction.DENY
    assert "exceed" in policy.reason.lower()


def test_evaluate_request_throttle_near_limit(engine):
    engine.set_budget("agent-1", limit=10.0, critical_threshold=0.9)
    engine.record_spend("agent-1", 8.5)
    policy = engine.evaluate_request("agent-1", estimated_cost=0.6)
    assert policy.action == ThrottleAction.THROTTLE


def test_evaluate_request_no_budget(engine):
    policy = engine.evaluate_request("agent-1", estimated_cost=100.0)
    assert policy.action == ThrottleAction.ALLOW
    assert "no budget" in policy.reason.lower()


def test_circuit_breaker_stays_closed_below_threshold(engine):
    cb = engine.trip_circuit_breaker("agent-1")
    assert cb.status == CircuitBreakerStatus.CLOSED
    assert cb.failure_count == 1

    cb = engine.trip_circuit_breaker("agent-1")
    assert cb.status == CircuitBreakerStatus.CLOSED
    assert cb.failure_count == 2


def test_circuit_breaker_opens_at_threshold(engine):
    for _ in range(3):
        cb = engine.trip_circuit_breaker("agent-1")
    assert cb.status == CircuitBreakerStatus.OPEN
    assert cb.failure_count == 3


def test_circuit_breaker_denies_requests(engine):
    engine.set_budget("agent-1", limit=100.0)
    for _ in range(3):
        engine.trip_circuit_breaker("agent-1")

    policy = engine.evaluate_request("agent-1", estimated_cost=0.01)
    assert policy.action == ThrottleAction.DENY
    assert "circuit breaker" in policy.reason.lower()


def test_reset_circuit_breaker(engine):
    for _ in range(3):
        engine.trip_circuit_breaker("agent-1")
    cb = engine.reset_circuit_breaker("agent-1")
    assert cb.status == CircuitBreakerStatus.CLOSED
    assert cb.failure_count == 0


def test_forecast_no_data(engine):
    engine.set_budget("agent-1", limit=10.0)
    forecast = engine.forecast("agent-1")
    assert forecast.burn_rate_per_hour == 0.0
    assert forecast.confidence == 0.0


def test_forecast_with_spend(engine):
    engine.set_budget("agent-1", limit=10.0)
    engine.record_spend("agent-1", 1.0)
    engine.record_spend("agent-1", 1.0)
    forecast = engine.forecast("agent-1")
    assert forecast.current_spend == 2.0
    assert forecast.burn_rate_per_hour > 0
    assert forecast.hours_until_exhaustion is not None


def test_alert_warning_threshold(engine):
    engine.set_budget("agent-1", limit=10.0, warning_threshold=0.8)
    engine.record_spend("agent-1", 8.5)
    alerts = engine.get_alerts("agent-1")
    assert len(alerts) >= 1
    kinds = [a.kind for a in alerts]
    assert BudgetAlertKind.THRESHOLD_WARNING in kinds or BudgetAlertKind.THRESHOLD_CRITICAL in kinds


def test_alert_budget_exhausted(engine):
    engine.set_budget("agent-1", limit=1.0)
    engine.record_spend("agent-1", 1.5)
    alerts = engine.get_alerts("agent-1")
    kinds = [a.kind for a in alerts]
    assert BudgetAlertKind.BUDGET_EXHAUSTED in kinds


def test_get_summary(engine):
    engine.set_budget("agent-1", limit=10.0)
    engine.set_budget("agent-2", limit=5.0)
    engine.record_spend("agent-1", 2.0)
    engine.record_spend("agent-2", 1.0)

    summary = engine.get_summary()
    assert summary["total_spend"] == 3.0
    assert summary["total_records"] == 2
    assert summary["active_budgets"] == 2
    assert "agent-1" in summary["by_agent"]


def test_multiple_agents_isolated(engine):
    engine.set_budget("agent-1", limit=5.0)
    engine.set_budget("agent-2", limit=5.0)
    engine.record_spend("agent-1", 4.0)
    engine.record_spend("agent-2", 1.0)

    assert engine.get_utilization("agent-1") == pytest.approx(0.8)
    assert engine.get_utilization("agent-2") == pytest.approx(0.2)


def test_get_circuit_breaker_none(engine):
    assert engine.get_circuit_breaker("agent-1") is None


def test_forecast_projected_spend(engine):
    engine.set_budget("agent-1", limit=100.0, period=BudgetPeriod.DAILY)
    for _ in range(10):
        engine.record_spend("agent-1", 0.5)
    forecast = engine.forecast("agent-1")
    assert forecast.projected_spend > 0
    assert forecast.confidence > 0
