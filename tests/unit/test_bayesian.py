"""Tests for Bayesian optimization with GP surrogates."""

from __future__ import annotations

import pytest

from reins.bayesian import (
    AcquisitionFunction,
    BayesianOptimizer,
    BayesianStats,
    OptimizationResult,
    OptimizationStatus,
    Parameter,
    ParameterKind,
    SearchSpace,
    Trial,
)


@pytest.fixture
def optimizer() -> BayesianOptimizer:
    return BayesianOptimizer(random_seed=42)


@pytest.fixture
def space(optimizer) -> SearchSpace:
    return optimizer.define_space("test", [
        Parameter(name="temperature", lower=0.0, upper=2.0),
        Parameter(name="top_p", lower=0.0, upper=1.0),
    ])


def test_define_space(optimizer, space):
    assert optimizer.get_space(space.space_id) is not None


def test_get_space_not_found(optimizer):
    assert optimizer.get_space("nonexistent") is None


def test_suggest_random_initial(optimizer, space):
    params = optimizer.suggest(space.space_id)
    assert "temperature" in params
    assert "top_p" in params
    assert 0.0 <= params["temperature"] <= 2.0
    assert 0.0 <= params["top_p"] <= 1.0


def test_suggest_uses_gp_after_warmup(optimizer, space):
    for i in range(5):
        params = optimizer.suggest(space.space_id)
        optimizer.report(space.space_id, params, objective=params["temperature"] * 0.5)
    params = optimizer.suggest(space.space_id)
    assert "temperature" in params


def test_report_trial(optimizer, space):
    trial = optimizer.report(space.space_id, {"temperature": 0.7, "top_p": 0.9}, 0.85)
    assert trial.objective == 0.85
    assert trial.iteration == 0


def test_report_increments_iteration(optimizer, space):
    optimizer.report(space.space_id, {"temperature": 0.5}, 0.5)
    trial = optimizer.report(space.space_id, {"temperature": 0.7}, 0.7)
    assert trial.iteration == 1


def test_get_best(optimizer, space):
    optimizer.report(space.space_id, {"temperature": 0.5}, 0.3)
    optimizer.report(space.space_id, {"temperature": 0.8}, 0.9)
    optimizer.report(space.space_id, {"temperature": 0.6}, 0.5)
    best = optimizer.get_best(space.space_id)
    assert best.objective == 0.9


def test_get_best_empty(optimizer, space):
    assert optimizer.get_best(space.space_id) is None


def test_get_trials(optimizer, space):
    optimizer.report(space.space_id, {"temperature": 0.5}, 0.3)
    optimizer.report(space.space_id, {"temperature": 0.8}, 0.9)
    assert len(optimizer.get_trials(space.space_id)) == 2


def test_get_result(optimizer, space):
    for i in range(5):
        optimizer.report(space.space_id, {"temperature": i * 0.2}, i * 0.2)
    result = optimizer.get_result(space.space_id)
    assert result.total_trials == 5
    assert result.best_objective == pytest.approx(0.8)


def test_get_result_empty(optimizer, space):
    result = optimizer.get_result(space.space_id)
    assert result.status == OptimizationStatus.EXPLORING


def test_convergence_detection(optimizer, space):
    for _ in range(10):
        optimizer.report(space.space_id, {"temperature": 0.7, "top_p": 0.9}, 0.85)
    result = optimizer.get_result(space.space_id)
    assert result.status == OptimizationStatus.CONVERGED


def test_integer_parameter(optimizer):
    space = optimizer.define_space("int_test", [
        Parameter(name="retries", kind=ParameterKind.INTEGER, lower=1, upper=10),
    ])
    params = optimizer.suggest(space.space_id)
    assert params["retries"] == int(params["retries"])


def test_log_scale_parameter(optimizer):
    space = optimizer.define_space("log_test", [
        Parameter(name="lr", kind=ParameterKind.LOG_SCALE, lower=0.0001, upper=1.0),
    ])
    params = optimizer.suggest(space.space_id)
    assert 0.0001 <= params["lr"] <= 1.0


def test_ucb_acquisition():
    opt = BayesianOptimizer(
        acquisition=AcquisitionFunction.UPPER_CONFIDENCE_BOUND, random_seed=42,
    )
    space = opt.define_space("ucb", [Parameter(name="x", lower=0.0, upper=1.0)])
    for i in range(5):
        params = opt.suggest(space.space_id)
        opt.report(space.space_id, params, objective=params["x"])
    params = opt.suggest(space.space_id)
    assert "x" in params


def test_poi_acquisition():
    opt = BayesianOptimizer(
        acquisition=AcquisitionFunction.PROBABILITY_OF_IMPROVEMENT, random_seed=42,
    )
    space = opt.define_space("poi", [Parameter(name="x", lower=0.0, upper=1.0)])
    for i in range(5):
        params = opt.suggest(space.space_id)
        opt.report(space.space_id, params, objective=params["x"])
    params = opt.suggest(space.space_id)
    assert "x" in params


def test_optimization_improves(optimizer):
    space = optimizer.define_space("improve", [
        Parameter(name="x", lower=-5.0, upper=5.0),
    ])
    for _ in range(20):
        params = optimizer.suggest(space.space_id)
        objective = -(params["x"] - 2.0) ** 2 + 10
        optimizer.report(space.space_id, params, objective)
    best = optimizer.get_best(space.space_id)
    assert best.objective > 5.0


def test_stats_empty():
    opt = BayesianOptimizer()
    stats = opt.get_stats()
    assert stats.total_spaces == 0
    assert stats.total_trials == 0


def test_stats_with_data(optimizer, space):
    optimizer.report(space.space_id, {"temperature": 0.5}, 0.3)
    optimizer.report(space.space_id, {"temperature": 0.8}, 0.9)
    stats = optimizer.get_stats()
    assert stats.total_spaces == 1
    assert stats.total_trials == 2
    assert stats.best_objective == 0.9
