"""Tests for experiment framework with A/B testing and bandit optimization."""

from __future__ import annotations

import pytest

from reins.experiments import (
    AllocationStrategy,
    Experiment,
    ExperimentConclusion,
    ExperimentManager,
    ExperimentManagerStats,
    ExperimentStatus,
    SignificanceLevel,
    TrialResult,
    Variant,
    VariantOutcome,
    VariantStats,
)


@pytest.fixture
def manager() -> ExperimentManager:
    return ExperimentManager(epsilon=0.1)


@pytest.fixture
def two_variants() -> list[Variant]:
    return [
        Variant(name="control", description="baseline strategy"),
        Variant(name="treatment", description="new strategy"),
    ]


def test_create_experiment(manager, two_variants):
    exp = manager.create_experiment("test-exp", two_variants)
    assert exp.name == "test-exp"
    assert exp.status == ExperimentStatus.RUNNING
    assert len(exp.variants) == 2


def test_get_experiment(manager, two_variants):
    exp = manager.create_experiment("test-exp", two_variants)
    retrieved = manager.get_experiment(exp.experiment_id)
    assert retrieved is not None
    assert retrieved.experiment_id == exp.experiment_id


def test_get_experiment_not_found(manager):
    assert manager.get_experiment("nonexistent") is None


def test_allocate_variant_uniform(manager, two_variants):
    exp = manager.create_experiment("test", two_variants, allocation=AllocationStrategy.UNIFORM)
    v1 = manager.allocate_variant(exp.experiment_id)
    assert v1 is not None
    assert v1 in two_variants


def test_allocate_variant_balances_uniform(manager, two_variants):
    exp = manager.create_experiment("test", two_variants, allocation=AllocationStrategy.UNIFORM)
    allocations = {}
    for _ in range(10):
        v = manager.allocate_variant(exp.experiment_id)
        allocations[v.variant_id] = allocations.get(v.variant_id, 0) + 1
        manager.record_trial(exp.experiment_id, v.variant_id, VariantOutcome.SUCCESS)
    assert len(allocations) == 2
    assert all(c >= 4 for c in allocations.values())


def test_allocate_variant_epsilon_greedy(manager, two_variants):
    exp = manager.create_experiment(
        "test", two_variants, allocation=AllocationStrategy.EPSILON_GREEDY
    )
    v = manager.allocate_variant(exp.experiment_id)
    assert v is not None


def test_allocate_variant_thompson_sampling(manager, two_variants):
    exp = manager.create_experiment(
        "test", two_variants, allocation=AllocationStrategy.THOMPSON_SAMPLING
    )
    v = manager.allocate_variant(exp.experiment_id)
    assert v is not None


def test_allocate_variant_ucb(manager, two_variants):
    exp = manager.create_experiment("test", two_variants, allocation=AllocationStrategy.UCB)
    v = manager.allocate_variant(exp.experiment_id)
    assert v is not None


def test_allocate_variant_nonexistent_experiment(manager):
    assert manager.allocate_variant("nonexistent") is None


def test_allocate_variant_concluded_experiment(manager, two_variants):
    exp = manager.create_experiment("test", two_variants, min_trials=1)
    manager.record_trial(exp.experiment_id, two_variants[0].variant_id, VariantOutcome.SUCCESS)
    manager.conclude(exp.experiment_id)
    assert manager.allocate_variant(exp.experiment_id) is None


def test_allocate_variant_max_trials_reached(manager, two_variants):
    exp = manager.create_experiment("test", two_variants, max_trials=2)
    for v in two_variants:
        manager.record_trial(exp.experiment_id, v.variant_id, VariantOutcome.SUCCESS)
    assert manager.allocate_variant(exp.experiment_id) is None


def test_record_trial(manager, two_variants):
    exp = manager.create_experiment("test", two_variants)
    trial = manager.record_trial(
        exp.experiment_id, two_variants[0].variant_id,
        VariantOutcome.SUCCESS, metric_value=0.9, latency_ms=50.0
    )
    assert trial is not None
    assert trial.outcome == VariantOutcome.SUCCESS
    assert trial.metric_value == 0.9
    assert trial.latency_ms == 50.0


def test_record_trial_nonexistent_experiment(manager):
    assert manager.record_trial("nonexistent", "v1", VariantOutcome.SUCCESS) is None


def test_record_trial_concluded_experiment(manager, two_variants):
    exp = manager.create_experiment("test", two_variants, min_trials=1)
    manager.record_trial(exp.experiment_id, two_variants[0].variant_id, VariantOutcome.SUCCESS)
    manager.conclude(exp.experiment_id)
    assert manager.record_trial(
        exp.experiment_id, two_variants[0].variant_id, VariantOutcome.SUCCESS
    ) is None


def test_conclude_experiment(manager, two_variants):
    exp = manager.create_experiment("test", two_variants)
    for i in range(20):
        manager.record_trial(
            exp.experiment_id, two_variants[0].variant_id,
            VariantOutcome.SUCCESS, metric_value=0.9
        )
    for i in range(20):
        manager.record_trial(
            exp.experiment_id, two_variants[1].variant_id,
            VariantOutcome.FAILURE, metric_value=0.3
        )
    conclusion = manager.conclude(exp.experiment_id)
    assert conclusion is not None
    assert conclusion.winner_variant_id == two_variants[0].variant_id
    assert conclusion.confidence > 0.5


def test_conclude_sets_status(manager, two_variants):
    exp = manager.create_experiment("test", two_variants)
    manager.record_trial(exp.experiment_id, two_variants[0].variant_id, VariantOutcome.SUCCESS)
    manager.conclude(exp.experiment_id)
    updated = manager.get_experiment(exp.experiment_id)
    assert updated.status == ExperimentStatus.CONCLUDED


def test_conclude_nonexistent(manager):
    assert manager.conclude("nonexistent") is None


def test_conclude_no_trials(manager, two_variants):
    exp = manager.create_experiment("test", two_variants)
    conclusion = manager.conclude(exp.experiment_id)
    assert conclusion is not None
    assert conclusion.winner_variant_id is None


def test_pause_experiment(manager, two_variants):
    exp = manager.create_experiment("test", two_variants)
    assert manager.pause(exp.experiment_id)
    updated = manager.get_experiment(exp.experiment_id)
    assert updated.status == ExperimentStatus.PAUSED


def test_pause_nonexistent(manager):
    assert not manager.pause("nonexistent")


def test_pause_already_paused(manager, two_variants):
    exp = manager.create_experiment("test", two_variants)
    manager.pause(exp.experiment_id)
    assert not manager.pause(exp.experiment_id)


def test_resume_experiment(manager, two_variants):
    exp = manager.create_experiment("test", two_variants)
    manager.pause(exp.experiment_id)
    assert manager.resume(exp.experiment_id)
    updated = manager.get_experiment(exp.experiment_id)
    assert updated.status == ExperimentStatus.RUNNING


def test_resume_not_paused(manager, two_variants):
    exp = manager.create_experiment("test", two_variants)
    assert not manager.resume(exp.experiment_id)


def test_resume_nonexistent(manager):
    assert not manager.resume("nonexistent")


def test_get_variant_stats(manager, two_variants):
    exp = manager.create_experiment("test", two_variants)
    manager.record_trial(
        exp.experiment_id, two_variants[0].variant_id,
        VariantOutcome.SUCCESS, metric_value=0.9
    )
    manager.record_trial(
        exp.experiment_id, two_variants[0].variant_id,
        VariantOutcome.FAILURE, metric_value=0.2
    )
    stats = manager.get_variant_stats(exp.experiment_id)
    assert len(stats) == 2
    control_stats = next(s for s in stats if s.variant_id == two_variants[0].variant_id)
    assert control_stats.trial_count == 2
    assert control_stats.success_count == 1
    assert control_stats.success_rate == pytest.approx(0.5)


def test_get_variant_stats_nonexistent(manager):
    assert manager.get_variant_stats("nonexistent") == []


def test_get_stats_empty(manager):
    stats = manager.get_stats()
    assert stats.total_experiments == 0
    assert stats.running == 0
    assert stats.total_trials == 0


def test_get_stats_with_data(manager, two_variants):
    exp = manager.create_experiment("test", two_variants)
    manager.record_trial(exp.experiment_id, two_variants[0].variant_id, VariantOutcome.SUCCESS)
    manager.record_trial(exp.experiment_id, two_variants[1].variant_id, VariantOutcome.FAILURE)

    stats = manager.get_stats()
    assert stats.total_experiments == 1
    assert stats.running == 1
    assert stats.total_trials == 2
    assert stats.avg_trials_per_experiment == 2.0


def test_significance_very_high(manager, two_variants):
    exp = manager.create_experiment("test", two_variants)
    for _ in range(50):
        manager.record_trial(
            exp.experiment_id, two_variants[0].variant_id, VariantOutcome.SUCCESS
        )
    for _ in range(50):
        manager.record_trial(
            exp.experiment_id, two_variants[1].variant_id, VariantOutcome.FAILURE
        )
    conclusion = manager.conclude(exp.experiment_id)
    assert conclusion.significance in (SignificanceLevel.HIGH, SignificanceLevel.VERY_HIGH)


def test_significance_low_few_trials(manager, two_variants):
    exp = manager.create_experiment("test", two_variants)
    manager.record_trial(exp.experiment_id, two_variants[0].variant_id, VariantOutcome.SUCCESS)
    manager.record_trial(exp.experiment_id, two_variants[1].variant_id, VariantOutcome.FAILURE)
    conclusion = manager.conclude(exp.experiment_id)
    assert conclusion.significance == SignificanceLevel.LOW


def test_recommendation_clear_winner(manager, two_variants):
    exp = manager.create_experiment("test", two_variants)
    for _ in range(50):
        manager.record_trial(
            exp.experiment_id, two_variants[0].variant_id, VariantOutcome.SUCCESS
        )
    for _ in range(50):
        manager.record_trial(
            exp.experiment_id, two_variants[1].variant_id, VariantOutcome.FAILURE
        )
    conclusion = manager.conclude(exp.experiment_id)
    assert "control" in conclusion.recommendation
    assert "Deploy" in conclusion.recommendation or "statistically" in conclusion.recommendation


def test_recommendation_no_winner(manager, two_variants):
    exp = manager.create_experiment("test", two_variants)
    conclusion = manager.conclude(exp.experiment_id)
    assert "Insufficient" in conclusion.recommendation


def test_ucb_explores_untried_variants(manager):
    variants = [Variant(name=f"v{i}") for i in range(4)]
    exp = manager.create_experiment("test", variants, allocation=AllocationStrategy.UCB)
    manager.record_trial(exp.experiment_id, variants[0].variant_id, VariantOutcome.SUCCESS)
    v = manager.allocate_variant(exp.experiment_id)
    assert v.variant_id != variants[0].variant_id


def test_epsilon_greedy_exploits_best(manager, two_variants):
    mgr = ExperimentManager(epsilon=0.0)
    exp = mgr.create_experiment(
        "test", two_variants, allocation=AllocationStrategy.EPSILON_GREEDY
    )
    for _ in range(10):
        mgr.record_trial(exp.experiment_id, two_variants[0].variant_id, VariantOutcome.SUCCESS)
    for _ in range(10):
        mgr.record_trial(exp.experiment_id, two_variants[1].variant_id, VariantOutcome.FAILURE)
    v = mgr.allocate_variant(exp.experiment_id)
    assert v.variant_id == two_variants[0].variant_id


def test_empty_variants_returns_none(manager):
    exp = manager.create_experiment("test", [])
    assert manager.allocate_variant(exp.experiment_id) is None


def test_trial_metadata(manager, two_variants):
    exp = manager.create_experiment("test", two_variants)
    trial = manager.record_trial(
        exp.experiment_id, two_variants[0].variant_id,
        VariantOutcome.SUCCESS, metadata={"model": "gpt-4"}
    )
    assert trial.metadata == {"model": "gpt-4"}


def test_std_dev_computed(manager, two_variants):
    exp = manager.create_experiment("test", two_variants)
    for val in [0.7, 0.8, 0.9, 0.6, 0.85]:
        manager.record_trial(
            exp.experiment_id, two_variants[0].variant_id,
            VariantOutcome.SUCCESS, metric_value=val
        )
    stats = manager.get_variant_stats(exp.experiment_id)
    control = next(s for s in stats if s.variant_id == two_variants[0].variant_id)
    assert control.std_dev > 0


def test_multiple_experiments_independent(manager, two_variants):
    exp1 = manager.create_experiment("exp1", two_variants)
    exp2 = manager.create_experiment("exp2", two_variants)
    manager.record_trial(exp1.experiment_id, two_variants[0].variant_id, VariantOutcome.SUCCESS)

    stats1 = manager.get_variant_stats(exp1.experiment_id)
    stats2 = manager.get_variant_stats(exp2.experiment_id)
    assert sum(s.trial_count for s in stats1) == 1
    assert sum(s.trial_count for s in stats2) == 0
