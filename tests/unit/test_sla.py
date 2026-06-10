"""Tests for SLA enforcement engine."""

from __future__ import annotations

import pytest

from reins.sla import (
    DegradationAction,
    ErrorBudget,
    SlaEngine,
    SlaMetric,
    SlaStatus,
)


@pytest.fixture
def engine() -> SlaEngine:
    return SlaEngine()


def test_define_objective(engine):
    obj = engine.define_objective(SlaMetric.LATENCY_P95, target=200.0)
    assert obj.metric == SlaMetric.LATENCY_P95
    assert obj.target == 200.0


def test_record_measurement(engine):
    obj = engine.define_objective(SlaMetric.LATENCY_P95, target=200.0)
    m = engine.record_measurement(obj.objective_id, 150.0)
    assert m is not None
    assert m.value == 150.0


def test_record_measurement_nonexistent(engine):
    assert engine.record_measurement("fake", 100.0) is None


def test_status_healthy(engine):
    obj = engine.define_objective(SlaMetric.LATENCY_P95, target=200.0)
    for _ in range(5):
        engine.record_measurement(obj.objective_id, 100.0)
    assert engine.get_status(obj.objective_id) == SlaStatus.HEALTHY


def test_status_breached_latency(engine):
    obj = engine.define_objective(SlaMetric.LATENCY_P95, target=200.0)
    for _ in range(5):
        engine.record_measurement(obj.objective_id, 500.0)
    assert engine.get_status(obj.objective_id) == SlaStatus.BREACHED


def test_status_breached_error_rate(engine):
    obj = engine.define_objective(SlaMetric.ERROR_RATE, target=0.01)
    for _ in range(5):
        engine.record_measurement(obj.objective_id, 0.05)
    assert engine.get_status(obj.objective_id) == SlaStatus.BREACHED


def test_status_breached_throughput(engine):
    obj = engine.define_objective(SlaMetric.THROUGHPUT, target=1000.0)
    for _ in range(5):
        engine.record_measurement(obj.objective_id, 200.0)
    assert engine.get_status(obj.objective_id) == SlaStatus.BREACHED


def test_status_unknown_no_measurements(engine):
    obj = engine.define_objective(SlaMetric.LATENCY_P50, target=100.0)
    assert engine.get_status(obj.objective_id) == SlaStatus.UNKNOWN


def test_breach_detected(engine):
    obj = engine.define_objective(SlaMetric.LATENCY_P99, target=500.0)
    engine.record_measurement(obj.objective_id, 1000.0)
    breaches = engine.get_breaches(obj.objective_id)
    assert len(breaches) == 1
    assert breaches[0].actual == 1000.0


def test_breach_severity(engine):
    obj = engine.define_objective(SlaMetric.LATENCY_P99, target=100.0)
    engine.record_measurement(obj.objective_id, 200.0)
    breaches = engine.get_breaches()
    assert breaches[0].severity == pytest.approx(1.0, abs=0.01)


def test_error_budget_full(engine):
    obj = engine.define_objective(SlaMetric.ERROR_RATE, target=0.01)
    for _ in range(10):
        engine.record_measurement(obj.objective_id, 0.005)
    budget = engine.get_error_budget(obj.objective_id)
    assert budget.remaining == 1.0
    assert budget.consumed == 0.0


def test_error_budget_consumed(engine):
    obj = engine.define_objective(SlaMetric.ERROR_RATE, target=0.01)
    for _ in range(5):
        engine.record_measurement(obj.objective_id, 0.005)
    for _ in range(5):
        engine.record_measurement(obj.objective_id, 0.05)
    budget = engine.get_error_budget(obj.objective_id)
    assert budget.consumed == 0.5
    assert budget.remaining == 0.5


def test_error_budget_nonexistent(engine):
    assert engine.get_error_budget("fake") is None


def test_degradation_action_on_breach(engine):
    obj = engine.define_objective(SlaMetric.LATENCY_P99, target=100.0)
    for _ in range(5):
        engine.record_measurement(obj.objective_id, 500.0)
    action = engine.get_degradation_action(obj.objective_id)
    assert action == DegradationAction.SHED_LOAD


def test_degradation_none_when_healthy(engine):
    obj = engine.define_objective(SlaMetric.LATENCY_P99, target=100.0)
    for _ in range(5):
        engine.record_measurement(obj.objective_id, 50.0)
    action = engine.get_degradation_action(obj.objective_id)
    assert action == DegradationAction.NONE


def test_custom_degradation_policy(engine):
    engine.set_degradation_policy(SlaMetric.QUALITY_SCORE, DegradationAction.FALLBACK)
    obj = engine.define_objective(SlaMetric.QUALITY_SCORE, target=0.8)
    for _ in range(5):
        engine.record_measurement(obj.objective_id, 0.3)
    action = engine.get_degradation_action(obj.objective_id)
    assert action == DegradationAction.FALLBACK


def test_warning_status_latency(engine):
    obj = engine.define_objective(SlaMetric.LATENCY_P95, target=200.0, warning_threshold=180.0)
    for _ in range(5):
        engine.record_measurement(obj.objective_id, 190.0)
    assert engine.get_status(obj.objective_id) == SlaStatus.WARNING


def test_stats_empty():
    e = SlaEngine()
    stats = e.get_stats()
    assert stats.total_objectives == 0
    assert stats.total_breaches == 0


def test_stats_with_data(engine):
    obj1 = engine.define_objective(SlaMetric.LATENCY_P95, target=200.0)
    obj2 = engine.define_objective(SlaMetric.ERROR_RATE, target=0.01)
    for _ in range(5):
        engine.record_measurement(obj1.objective_id, 100.0)
        engine.record_measurement(obj2.objective_id, 0.05)
    stats = engine.get_stats()
    assert stats.total_objectives == 2
    assert stats.healthy >= 1
    assert stats.breached >= 1
    assert stats.total_measurements == 10
