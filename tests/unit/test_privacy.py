"""Tests for differential privacy with epsilon-delta guarantees."""

from __future__ import annotations

import pytest

from reins.privacy import (
    BudgetStatus,
    DataRecord,
    DifferentialPrivacyEngine,
    PrivacyBudget,
    PrivacyLevel,
    PrivacyMechanism,
    PrivacyQuery,
    PrivacyStats,
)


@pytest.fixture
def engine() -> DifferentialPrivacyEngine:
    return DifferentialPrivacyEngine(default_epsilon=1.0, random_seed=42)


@pytest.fixture
def data(engine) -> list[DataRecord]:
    r1 = engine.register_data("salary", 75000.0, sensitivity=50000.0, level=PrivacyLevel.HIGH_SENSITIVITY)
    r2 = engine.register_data("age", 35.0, sensitivity=100.0, level=PrivacyLevel.LOW_SENSITIVITY)
    r3 = engine.register_data("score", 0.85, sensitivity=1.0, level=PrivacyLevel.MODERATE_SENSITIVITY)
    return [r1, r2, r3]


def test_register_data(engine):
    record = engine.register_data("test", 42.0)
    assert engine.get_record("test") is not None


def test_get_record_not_found(engine):
    assert engine.get_record("nonexistent") is None


def test_allocate_budget(engine):
    budget = engine.allocate_budget("agent-1", epsilon=2.0)
    assert budget.epsilon_total == 2.0
    assert budget.epsilon_spent == 0.0


def test_get_budget(engine):
    engine.allocate_budget("agent-1")
    assert engine.get_budget("agent-1") is not None


def test_budget_status_available(engine):
    engine.allocate_budget("agent-1")
    assert engine.get_budget_status("agent-1") == BudgetStatus.AVAILABLE


def test_query_returns_noisy_value(engine, data):
    engine.allocate_budget("agent-1")
    query = engine.query("agent-1", "salary")
    assert query is not None
    assert query.noisy_value != query.true_value


def test_query_adds_noise(engine, data):
    engine.allocate_budget("agent-1")
    query = engine.query("agent-1", "salary")
    assert query.noise_added != 0.0


def test_query_spends_budget(engine, data):
    engine.allocate_budget("agent-1")
    engine.query("agent-1", "salary")
    budget = engine.get_budget("agent-1")
    assert budget.epsilon_spent > 0


def test_query_nonexistent_data(engine):
    engine.allocate_budget("agent-1")
    assert engine.query("agent-1", "nonexistent") is None


def test_query_exhausted_budget(engine, data):
    engine.allocate_budget("agent-1", epsilon=0.1)
    engine.query("agent-1", "salary")
    result = engine.query("agent-1", "salary")
    assert result is None


def test_query_auto_allocates_budget(engine, data):
    query = engine.query("agent-1", "age")
    assert query is not None


def test_laplace_mechanism(engine, data):
    engine.allocate_budget("agent-1", epsilon=5.0)
    query = engine.query("agent-1", "score", mechanism=PrivacyMechanism.LAPLACE)
    assert query.mechanism == PrivacyMechanism.LAPLACE


def test_gaussian_mechanism(engine, data):
    engine.allocate_budget("agent-1", epsilon=5.0)
    query = engine.query("agent-1", "score", mechanism=PrivacyMechanism.GAUSSIAN)
    assert query.mechanism == PrivacyMechanism.GAUSSIAN
    assert query.delta_cost > 0


def test_randomized_response(engine, data):
    engine.allocate_budget("agent-1", epsilon=5.0)
    query = engine.query("agent-1", "score", mechanism=PrivacyMechanism.RANDOMIZED_RESPONSE)
    assert query is not None


def test_privacy_loss_tracking(engine, data):
    engine.allocate_budget("agent-1", epsilon=5.0)
    engine.query("agent-1", "age")
    engine.query("agent-1", "score")
    loss = engine.compute_privacy_loss("agent-1")
    assert loss > 0


def test_remaining_budget(engine, data):
    engine.allocate_budget("agent-1", epsilon=2.0)
    engine.query("agent-1", "age")
    remaining = engine.remaining_budget("agent-1")
    assert remaining < 2.0
    assert remaining > 0


def test_remaining_budget_no_allocation(engine):
    remaining = engine.remaining_budget("new-agent")
    assert remaining == 1.0


def test_get_queries_all(engine, data):
    engine.allocate_budget("a", epsilon=5.0)
    engine.allocate_budget("b", epsilon=5.0)
    engine.query("a", "age")
    engine.query("b", "score")
    assert len(engine.get_queries()) == 2


def test_get_queries_by_agent(engine, data):
    engine.allocate_budget("a", epsilon=5.0)
    engine.allocate_budget("b", epsilon=5.0)
    engine.query("a", "age")
    engine.query("b", "score")
    assert len(engine.get_queries(agent_id="a")) == 1


def test_higher_sensitivity_more_noise(engine):
    engine.register_data("low_sens", 100.0, sensitivity=1.0)
    engine.register_data("high_sens", 100.0, sensitivity=1000.0)
    engine.allocate_budget("agent-1", epsilon=10.0)
    noises = []
    for _ in range(50):
        q = engine.query("agent-1", "low_sens", epsilon=0.1)
        noises.append(abs(q.noise_added))
    avg_low = sum(noises) / len(noises)
    engine.allocate_budget("agent-2", epsilon=10.0)
    noises2 = []
    for _ in range(50):
        q = engine.query("agent-2", "high_sens", epsilon=0.1)
        noises2.append(abs(q.noise_added))
    avg_high = sum(noises2) / len(noises2)
    assert avg_high > avg_low


def test_budget_status_low(engine, data):
    engine.allocate_budget("agent-1", epsilon=0.35)
    engine.query("agent-1", "score")
    status = engine.get_budget_status("agent-1")
    assert status in (BudgetStatus.LOW, BudgetStatus.EXHAUSTED)


def test_stats_empty():
    eng = DifferentialPrivacyEngine()
    stats = eng.get_stats()
    assert stats.total_agents == 0
    assert stats.total_queries == 0


def test_stats_with_data(engine, data):
    engine.allocate_budget("a", epsilon=5.0)
    engine.query("a", "age")
    engine.query("a", "score")
    stats = engine.get_stats()
    assert stats.total_agents == 1
    assert stats.total_queries == 2
    assert stats.total_records == 3
    assert stats.avg_epsilon_spent > 0
