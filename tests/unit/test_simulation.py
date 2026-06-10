"""Tests for simulation engine with Monte Carlo strategy testing."""

from __future__ import annotations

import pytest

from reins.simulation import (
    OutcomeKind,
    Scenario,
    ScenarioKind,
    SimulationBatch,
    SimulationEngine,
    SimulationResult,
    SimulationRun,
    SimulationStats,
    SimulationStatus,
    StrategyProfile,
)


@pytest.fixture
def engine() -> SimulationEngine:
    return SimulationEngine(default_iterations=50)


@pytest.fixture
def scenario() -> Scenario:
    return Scenario(name="normal-load", kind=ScenarioKind.NORMAL)


@pytest.fixture
def strategy() -> StrategyProfile:
    return StrategyProfile(strategy_id="strat-1", name="aggressive")


def test_register_scenario(engine, scenario):
    registered = engine.register_scenario(scenario)
    assert engine.get_scenario(registered.scenario_id) is not None


def test_get_scenario_not_found(engine):
    assert engine.get_scenario("nonexistent") is None


def test_register_strategy(engine, strategy):
    registered = engine.register_strategy(strategy)
    assert engine.get_strategy(registered.strategy_id) is not None


def test_get_strategy_not_found(engine):
    assert engine.get_strategy("nonexistent") is None


def test_run_batch(engine, scenario, strategy):
    engine.register_scenario(scenario)
    engine.register_strategy(strategy)
    batch = engine.run_batch(scenario.scenario_id, strategy.strategy_id)
    assert batch is not None
    assert batch.status == SimulationStatus.COMPLETED
    assert len(batch.runs) == 50


def test_run_batch_custom_iterations(engine, scenario, strategy):
    engine.register_scenario(scenario)
    engine.register_strategy(strategy)
    batch = engine.run_batch(scenario.scenario_id, strategy.strategy_id, iterations=10)
    assert len(batch.runs) == 10


def test_run_batch_missing_scenario(engine, strategy):
    engine.register_strategy(strategy)
    assert engine.run_batch("nonexistent", strategy.strategy_id) is None


def test_run_batch_missing_strategy(engine, scenario):
    engine.register_scenario(scenario)
    assert engine.run_batch(scenario.scenario_id, "nonexistent") is None


def test_get_result(engine, scenario, strategy):
    engine.register_scenario(scenario)
    engine.register_strategy(strategy)
    batch = engine.run_batch(scenario.scenario_id, strategy.strategy_id)
    result = engine.get_result(batch.batch_id)
    assert result is not None
    assert result.total_runs == 50
    assert 0.0 <= result.success_rate <= 1.0
    assert result.avg_score > 0


def test_get_result_not_found(engine):
    assert engine.get_result("nonexistent") is None


def test_result_has_latency_stats(engine, scenario, strategy):
    engine.register_scenario(scenario)
    engine.register_strategy(strategy)
    batch = engine.run_batch(scenario.scenario_id, strategy.strategy_id)
    result = engine.get_result(batch.batch_id)
    assert result.avg_latency_ms > 0
    assert result.p95_latency_ms >= result.avg_latency_ms


def test_result_by_outcome(engine, scenario, strategy):
    engine.register_scenario(scenario)
    engine.register_strategy(strategy)
    batch = engine.run_batch(scenario.scenario_id, strategy.strategy_id)
    result = engine.get_result(batch.batch_id)
    total_from_outcomes = sum(result.by_outcome.values())
    assert total_from_outcomes == result.total_runs


def test_compare_strategies(engine, scenario):
    engine.register_scenario(scenario)
    s1 = engine.register_strategy(StrategyProfile(strategy_id="s1", name="conservative"))
    s2 = engine.register_strategy(StrategyProfile(strategy_id="s2", name="aggressive"))
    results = engine.compare_strategies(scenario.scenario_id, iterations=20)
    assert len(results) == 2
    assert results[0].success_rate >= results[1].success_rate


def test_compare_strategies_subset(engine, scenario):
    engine.register_scenario(scenario)
    engine.register_strategy(StrategyProfile(strategy_id="s1", name="a"))
    engine.register_strategy(StrategyProfile(strategy_id="s2", name="b"))
    engine.register_strategy(StrategyProfile(strategy_id="s3", name="c"))
    results = engine.compare_strategies(scenario.scenario_id, strategy_ids=["s1", "s2"])
    assert len(results) == 2


def test_custom_evaluator(engine, scenario, strategy):
    engine.register_scenario(scenario)
    engine.register_strategy(strategy)

    def always_succeed(sc, st, i):
        return SimulationRun(
            scenario_id=sc.scenario_id,
            strategy_id=st.strategy_id,
            iteration=i,
            outcome=OutcomeKind.SUCCESS,
            score=1.0,
            latency_ms=10.0,
        )

    engine.register_evaluator(strategy.strategy_id, always_succeed)
    batch = engine.run_batch(scenario.scenario_id, strategy.strategy_id, iterations=10)
    result = engine.get_result(batch.batch_id)
    assert result.success_rate == 1.0
    assert result.avg_score == 1.0


def test_custom_evaluator_failure(engine, scenario, strategy):
    engine.register_scenario(scenario)
    engine.register_strategy(strategy)

    def always_fail(sc, st, i):
        return SimulationRun(
            scenario_id=sc.scenario_id,
            strategy_id=st.strategy_id,
            iteration=i,
            outcome=OutcomeKind.FAILURE,
            score=0.0,
            latency_ms=5.0,
        )

    engine.register_evaluator(strategy.strategy_id, always_fail)
    batch = engine.run_batch(scenario.scenario_id, strategy.strategy_id, iterations=10)
    result = engine.get_result(batch.batch_id)
    assert result.success_rate == 0.0
    assert result.failure_count == 10


def test_stress_scenario_lower_success(engine, strategy):
    normal = Scenario(name="normal", kind=ScenarioKind.NORMAL)
    stress = Scenario(name="stress", kind=ScenarioKind.STRESS)
    engine.register_scenario(normal)
    engine.register_scenario(stress)
    engine.register_strategy(strategy)

    batch_normal = engine.run_batch(normal.scenario_id, strategy.strategy_id, iterations=200)
    batch_stress = engine.run_batch(stress.scenario_id, strategy.strategy_id, iterations=200)
    r_normal = engine.get_result(batch_normal.batch_id)
    r_stress = engine.get_result(batch_stress.batch_id)
    assert r_normal.success_rate > r_stress.success_rate


def test_get_batches_all(engine, scenario, strategy):
    engine.register_scenario(scenario)
    engine.register_strategy(strategy)
    engine.run_batch(scenario.scenario_id, strategy.strategy_id, iterations=5)
    engine.run_batch(scenario.scenario_id, strategy.strategy_id, iterations=5)
    assert len(engine.get_batches()) == 2


def test_get_batches_by_scenario(engine, strategy):
    s1 = engine.register_scenario(Scenario(name="s1", kind=ScenarioKind.NORMAL))
    s2 = engine.register_scenario(Scenario(name="s2", kind=ScenarioKind.STRESS))
    engine.register_strategy(strategy)
    engine.run_batch(s1.scenario_id, strategy.strategy_id, iterations=5)
    engine.run_batch(s2.scenario_id, strategy.strategy_id, iterations=5)
    batches = engine.get_batches(scenario_id=s1.scenario_id)
    assert len(batches) == 1


def test_get_batches_by_strategy(engine, scenario):
    engine.register_scenario(scenario)
    st1 = engine.register_strategy(StrategyProfile(strategy_id="st1", name="a"))
    st2 = engine.register_strategy(StrategyProfile(strategy_id="st2", name="b"))
    engine.run_batch(scenario.scenario_id, "st1", iterations=5)
    engine.run_batch(scenario.scenario_id, "st2", iterations=5)
    batches = engine.get_batches(strategy_id="st1")
    assert len(batches) == 1


def test_std_dev_computed(engine, scenario, strategy):
    engine.register_scenario(scenario)
    engine.register_strategy(strategy)
    batch = engine.run_batch(scenario.scenario_id, strategy.strategy_id, iterations=50)
    result = engine.get_result(batch.batch_id)
    assert result.std_dev_score >= 0


def test_stats_empty():
    eng = SimulationEngine()
    stats = eng.get_stats()
    assert stats.total_scenarios == 0
    assert stats.total_runs == 0


def test_stats_with_data(engine, scenario, strategy):
    engine.register_scenario(scenario)
    engine.register_strategy(strategy)
    engine.run_batch(scenario.scenario_id, strategy.strategy_id, iterations=10)
    stats = engine.get_stats()
    assert stats.total_scenarios == 1
    assert stats.total_strategies == 1
    assert stats.total_batches == 1
    assert stats.total_runs == 10
    assert 0.0 <= stats.avg_success_rate <= 1.0
    assert ScenarioKind.NORMAL.value in stats.by_scenario_kind
