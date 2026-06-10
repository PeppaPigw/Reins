"""Tests for speculative execution engine."""

from __future__ import annotations

import pytest

from reins.speculative import (
    Candidate,
    CandidateStatus,
    SelectionCriteria,
    SpeculativeExecutor,
    SpeculativeResult,
    SpeculativeStrategy,
    SpeculativeTask,
)


@pytest.fixture
def executor() -> SpeculativeExecutor:
    ex = SpeculativeExecutor()
    ex.register_executor("fast", lambda name, ctx: "fast_result")
    ex.register_executor("slow", lambda name, ctx: "slow_result")
    ex.register_executor("best", lambda name, ctx: "best_result")
    ex.register_executor("failing", lambda name, ctx: (_ for _ in ()).throw(RuntimeError("boom")))
    ex.register_scorer("fast", lambda output: 0.6)
    ex.register_scorer("slow", lambda output: 0.7)
    ex.register_scorer("best", lambda output: 0.95)
    return ex


def _task(
    strategy=SpeculativeStrategy.BEST_OF_N,
    selection=SelectionCriteria.HIGHEST_SCORE,
    candidates=(),
    min_quality=0.0,
):
    return SpeculativeTask(
        description="test task",
        strategy=strategy,
        selection=selection,
        candidates=candidates,
        min_quality_threshold=min_quality,
    )


def _candidate(approach="fast", cost=0.01):
    return Candidate(approach_name=approach, cost=cost)


@pytest.mark.asyncio
async def test_empty_candidates(executor):
    task = _task(candidates=())
    result = await executor.execute(task)
    assert result.selected_candidate is None
    assert "No candidates" in result.selection_reason


@pytest.mark.asyncio
async def test_best_of_n_selects_highest_score(executor):
    task = _task(candidates=(
        _candidate("fast", 0.01),
        _candidate("slow", 0.02),
        _candidate("best", 0.05),
    ))
    result = await executor.execute(task)
    assert result.selected_candidate is not None
    assert result.selected_candidate.approach_name == "best"
    assert result.selected_candidate.quality_score == 0.95


@pytest.mark.asyncio
async def test_race_stops_at_first_success(executor):
    task = _task(
        strategy=SpeculativeStrategy.RACE,
        candidates=(
            _candidate("fast"),
            _candidate("slow"),
            _candidate("best"),
        ),
    )
    result = await executor.execute(task)
    assert result.selected_candidate is not None
    assert result.selected_candidate.approach_name == "fast"
    assert len(result.all_candidates) == 1


@pytest.mark.asyncio
async def test_race_skips_failures(executor):
    task = _task(
        strategy=SpeculativeStrategy.RACE,
        candidates=(
            _candidate("failing"),
            _candidate("fast"),
        ),
    )
    result = await executor.execute(task)
    assert result.selected_candidate is not None
    assert result.selected_candidate.approach_name == "fast"
    assert len(result.all_candidates) == 2


@pytest.mark.asyncio
async def test_cascading_stops_when_quality_met(executor):
    task = _task(
        strategy=SpeculativeStrategy.CASCADING,
        candidates=(
            _candidate("fast", 0.01),
            _candidate("best", 0.10),
        ),
        min_quality=0.5,
    )
    result = await executor.execute(task)
    assert result.selected_candidate is not None
    assert result.selected_candidate.approach_name == "fast"
    assert len(result.all_candidates) == 1


@pytest.mark.asyncio
async def test_cascading_escalates_when_quality_low(executor):
    task = _task(
        strategy=SpeculativeStrategy.CASCADING,
        candidates=(
            _candidate("fast", 0.01),
            _candidate("best", 0.10),
        ),
        min_quality=0.9,
    )
    result = await executor.execute(task)
    assert result.selected_candidate is not None
    assert result.selected_candidate.approach_name == "best"
    assert len(result.all_candidates) == 2


@pytest.mark.asyncio
async def test_selection_lowest_cost(executor):
    task = _task(
        selection=SelectionCriteria.LOWEST_COST,
        candidates=(
            _candidate("fast", 0.01),
            _candidate("best", 0.10),
        ),
    )
    result = await executor.execute(task)
    assert result.selected_candidate is not None
    assert result.selected_candidate.approach_name == "fast"


@pytest.mark.asyncio
async def test_selection_fastest(executor):
    task = _task(
        selection=SelectionCriteria.FASTEST,
        candidates=(
            _candidate("fast"),
            _candidate("slow"),
        ),
    )
    result = await executor.execute(task)
    assert result.selected_candidate is not None


@pytest.mark.asyncio
async def test_selection_majority_vote(executor):
    ex = SpeculativeExecutor()
    ex.register_executor("a", lambda n, c: "same")
    ex.register_executor("b", lambda n, c: "same")
    ex.register_executor("c", lambda n, c: "different")
    ex.register_scorer("a", lambda o: 0.7)
    ex.register_scorer("b", lambda o: 0.8)
    ex.register_scorer("c", lambda o: 0.9)

    task = _task(
        selection=SelectionCriteria.MAJORITY_VOTE,
        candidates=(
            Candidate(approach_name="a"),
            Candidate(approach_name="b"),
            Candidate(approach_name="c"),
        ),
    )
    result = await ex.execute(task)
    assert result.selected_candidate is not None
    assert result.selected_candidate.approach_name == "b"


@pytest.mark.asyncio
async def test_selection_weighted_ensemble(executor):
    task = _task(
        selection=SelectionCriteria.WEIGHTED_ENSEMBLE,
        candidates=(
            _candidate("fast"),
            _candidate("best"),
        ),
    )
    result = await executor.execute(task)
    assert result.selected_candidate is not None


@pytest.mark.asyncio
async def test_all_candidates_fail(executor):
    task = _task(candidates=(
        _candidate("failing"),
        _candidate("failing"),
    ))
    result = await executor.execute(task)
    assert result.selected_candidate is None
    assert "No candidate met" in result.selection_reason


@pytest.mark.asyncio
async def test_missing_executor(executor):
    task = _task(candidates=(_candidate("nonexistent"),))
    result = await executor.execute(task)
    assert result.all_candidates[0].status == CandidateStatus.FAILED
    assert "No executor" in result.all_candidates[0].error


@pytest.mark.asyncio
async def test_no_scorer_defaults_to_half(executor):
    ex = SpeculativeExecutor()
    ex.register_executor("plain", lambda n, c: "output")
    task = _task(candidates=(Candidate(approach_name="plain"),))
    result = await ex.execute(task)
    assert result.selected_candidate.quality_score == 0.5


@pytest.mark.asyncio
async def test_total_cost_accumulated(executor):
    task = _task(candidates=(
        _candidate("fast", 0.01),
        _candidate("slow", 0.02),
        _candidate("best", 0.05),
    ))
    result = await executor.execute(task)
    assert result.total_cost == pytest.approx(0.08)


@pytest.mark.asyncio
async def test_latency_tracked(executor):
    task = _task(candidates=(_candidate("fast"),))
    result = await executor.execute(task)
    assert result.total_latency_ms > 0
    assert result.all_candidates[0].latency_ms > 0


@pytest.mark.asyncio
async def test_strategy_recorded_in_result(executor):
    task = _task(
        strategy=SpeculativeStrategy.CONSENSUS,
        candidates=(_candidate("fast"),),
    )
    result = await executor.execute(task)
    assert result.strategy_used == SpeculativeStrategy.CONSENSUS


@pytest.mark.asyncio
async def test_min_quality_threshold_filters(executor):
    task = _task(
        candidates=(
            _candidate("fast"),
            _candidate("best"),
        ),
        min_quality=0.9,
    )
    result = await executor.execute(task)
    assert result.selected_candidate.approach_name == "best"


@pytest.mark.asyncio
async def test_stats_empty():
    ex = SpeculativeExecutor()
    stats = ex.get_stats()
    assert stats["total_executions"] == 0


@pytest.mark.asyncio
async def test_stats_after_executions(executor):
    task = _task(candidates=(_candidate("fast"), _candidate("best")))
    await executor.execute(task)
    await executor.execute(task)
    stats = executor.get_stats()
    assert stats["total_executions"] == 2
    assert stats["avg_candidates"] == 2.0
    assert stats["selection_rate"] == 1.0
    assert stats["total_cost"] > 0


@pytest.mark.asyncio
async def test_candidate_timestamps(executor):
    task = _task(candidates=(_candidate("fast"),))
    result = await executor.execute(task)
    c = result.all_candidates[0]
    assert c.started_at is not None
    assert c.completed_at is not None


@pytest.mark.asyncio
async def test_failed_candidate_has_error(executor):
    task = _task(candidates=(_candidate("failing"),))
    result = await executor.execute(task)
    c = result.all_candidates[0]
    assert c.status == CandidateStatus.FAILED
    assert c.error == "boom"
