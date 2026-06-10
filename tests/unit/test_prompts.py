"""Tests for prompt optimization engine."""

from __future__ import annotations

import pytest

from reins.prompts import (
    FewShotExample,
    OptimizationStrategy,
    OutcomeSignal,
    PromptOptimizer,
    PromptOutcome,
    PromptTemplate,
)


@pytest.fixture
def optimizer() -> PromptOptimizer:
    return PromptOptimizer()


@pytest.fixture
def template() -> PromptTemplate:
    return PromptTemplate(name="code_review", content="Review this code: {code}")


def test_register_template(optimizer, template):
    optimizer.register_template(template)
    assert optimizer.template_count == 1
    assert optimizer.get_template(template.template_id) is not None


def test_get_nonexistent_template(optimizer):
    assert optimizer.get_template("nonexistent") is None


def test_record_outcome(optimizer, template):
    optimizer.register_template(template)
    outcome = PromptOutcome(
        template_id=template.template_id,
        signal=OutcomeSignal.SUCCESS,
        latency_ms=500,
        token_count=1000,
        cost=0.01,
    )
    optimizer.record_outcome(outcome)
    assert optimizer.outcome_count == 1


def test_success_rate(optimizer, template):
    optimizer.register_template(template)
    for signal in [OutcomeSignal.SUCCESS, OutcomeSignal.SUCCESS, OutcomeSignal.FAILURE]:
        optimizer.record_outcome(PromptOutcome(
            template_id=template.template_id, signal=signal,
        ))
    rate = optimizer.get_success_rate(template.template_id)
    assert rate == pytest.approx(2 / 3)


def test_success_rate_no_outcomes(optimizer):
    assert optimizer.get_success_rate("nonexistent") == 0.0


def test_avg_score(optimizer, template):
    optimizer.register_template(template)
    optimizer.record_outcome(PromptOutcome(
        template_id=template.template_id, signal=OutcomeSignal.SUCCESS,
    ))
    optimizer.record_outcome(PromptOutcome(
        template_id=template.template_id, signal=OutcomeSignal.PARTIAL,
    ))
    score = optimizer.get_avg_score(template.template_id)
    assert score == pytest.approx(0.75)


def test_select_few_shots_by_quality(optimizer):
    optimizer.add_example(FewShotExample(input_text="a", output_text="b", quality_score=0.5))
    optimizer.add_example(FewShotExample(input_text="c", output_text="d", quality_score=0.9))
    optimizer.add_example(FewShotExample(input_text="e", output_text="f", quality_score=0.7))

    selected = optimizer.select_few_shots("t1", max_examples=2)
    assert len(selected) == 2
    assert selected[0].quality_score == 0.9


def test_select_few_shots_by_tags(optimizer):
    optimizer.add_example(FewShotExample(input_text="a", output_text="b", tags=("python",), quality_score=0.8))
    optimizer.add_example(FewShotExample(input_text="c", output_text="d", tags=("rust",), quality_score=0.8))

    selected = optimizer.select_few_shots("t1", task_tags=("python",), max_examples=1)
    assert len(selected) == 1
    assert "python" in selected[0].tags


def test_select_few_shots_empty_pool(optimizer):
    assert optimizer.select_few_shots("t1") == ()


def test_create_variant(optimizer, template):
    optimizer.register_template(template)
    variant = optimizer.create_variant(
        template.template_id,
        OptimizationStrategy.TEMPLATE_REFINEMENT,
        "Improved: Review this code carefully: {code}",
    )
    assert variant.template_id == template.template_id
    assert variant.trial_count == 0


def test_record_variant_outcome(optimizer, template):
    optimizer.register_template(template)
    variant = optimizer.create_variant(
        template.template_id, OptimizationStrategy.FEW_SHOT_SELECTION, "v1",
    )
    updated = optimizer.record_variant_outcome(variant.variant_id, OutcomeSignal.SUCCESS)
    assert updated is not None
    assert updated.trial_count == 1
    assert updated.success_count == 1
    assert updated.score == 1.0


def test_record_variant_outcome_averaging(optimizer, template):
    optimizer.register_template(template)
    variant = optimizer.create_variant(
        template.template_id, OptimizationStrategy.TEMPLATE_REFINEMENT, "v1",
    )
    optimizer.record_variant_outcome(variant.variant_id, OutcomeSignal.SUCCESS)
    updated = optimizer.record_variant_outcome(variant.variant_id, OutcomeSignal.FAILURE)
    assert updated.trial_count == 2
    assert updated.score == pytest.approx(0.5)


def test_record_variant_outcome_nonexistent(optimizer):
    assert optimizer.record_variant_outcome("nonexistent", OutcomeSignal.SUCCESS) is None


def test_get_best_variant(optimizer, template):
    optimizer.register_template(template)
    v1 = optimizer.create_variant(template.template_id, OptimizationStrategy.TEMPLATE_REFINEMENT, "v1")
    v2 = optimizer.create_variant(template.template_id, OptimizationStrategy.TEMPLATE_REFINEMENT, "v2")

    for _ in range(3):
        optimizer.record_variant_outcome(v1.variant_id, OutcomeSignal.PARTIAL)
    for _ in range(3):
        optimizer.record_variant_outcome(v2.variant_id, OutcomeSignal.SUCCESS)

    best = optimizer.get_best_variant(template.template_id)
    assert best is not None
    assert best.variant_id == v2.variant_id


def test_get_best_variant_min_trials(optimizer, template):
    optimizer.register_template(template)
    v = optimizer.create_variant(template.template_id, OptimizationStrategy.TEMPLATE_REFINEMENT, "v1")
    optimizer.record_variant_outcome(v.variant_id, OutcomeSignal.SUCCESS)

    assert optimizer.get_best_variant(template.template_id, min_trials=5) is None


def test_optimize(optimizer, template):
    optimizer.register_template(template)
    v = optimizer.create_variant(template.template_id, OptimizationStrategy.CHAIN_OF_THOUGHT, "cot version")
    for _ in range(5):
        optimizer.record_variant_outcome(v.variant_id, OutcomeSignal.SUCCESS)

    result = optimizer.optimize(template.template_id)
    assert result.variants_tested == 1
    assert result.best_variant is not None
    assert result.strategy_used == OptimizationStrategy.CHAIN_OF_THOUGHT


def test_optimize_no_template(optimizer):
    result = optimizer.optimize("nonexistent")
    assert result.variants_tested == 0
    assert result.best_variant is None


def test_suggest_parameters(optimizer, template):
    optimizer.register_template(template)
    for _ in range(5):
        optimizer.record_outcome(PromptOutcome(
            template_id=template.template_id,
            signal=OutcomeSignal.SUCCESS,
            token_count=1000,
            latency_ms=500,
        ))

    params = optimizer.suggest_parameters(template.template_id)
    assert "recommended_max_tokens" in params
    assert params["recommended_max_tokens"] == 1200
    assert params["success_rate"] == 1.0


def test_suggest_parameters_no_data(optimizer):
    assert optimizer.suggest_parameters("nonexistent") == {}


def test_prune_examples(optimizer):
    optimizer.add_example(FewShotExample(input_text="a", output_text="b", quality_score=0.3))
    optimizer.add_example(FewShotExample(input_text="c", output_text="d", quality_score=0.8))
    optimizer.add_example(FewShotExample(input_text="e", output_text="f", quality_score=0.2))

    pruned = optimizer.prune_examples(min_quality=0.5)
    assert pruned == 2


def test_template_stats(optimizer, template):
    optimizer.register_template(template)
    optimizer.record_outcome(PromptOutcome(
        template_id=template.template_id, signal=OutcomeSignal.SUCCESS,
        latency_ms=100, token_count=500, cost=0.005,
    ))
    optimizer.record_outcome(PromptOutcome(
        template_id=template.template_id, signal=OutcomeSignal.FAILURE,
        latency_ms=200, token_count=800, cost=0.008,
    ))

    stats = optimizer.get_template_stats(template.template_id)
    assert stats["total_uses"] == 2
    assert stats["success_rate"] == 0.5
    assert stats["total_cost"] == pytest.approx(0.013)


def test_template_stats_no_data(optimizer):
    stats = optimizer.get_template_stats("nonexistent")
    assert stats["total_uses"] == 0
