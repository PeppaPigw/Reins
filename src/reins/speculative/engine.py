from __future__ import annotations

import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, Callable

from reins.speculative.types import (
    Candidate,
    CandidateStatus,
    SelectionCriteria,
    SpeculativeResult,
    SpeculativeStrategy,
    SpeculativeTask,
)


class SpeculativeExecutor:
    """Executes multiple approaches in parallel and selects the best result.

    Supports strategies: best-of-N, race (first success wins), consensus
    (majority vote), and cascading (try cheap first, escalate if needed).
    """

    def __init__(self) -> None:
        self._executors: dict[str, Callable[[str, dict[str, Any]], Any]] = {}
        self._scorers: dict[str, Callable[[Any], float]] = {}
        self._results: list[SpeculativeResult] = []

    def register_executor(self, name: str, fn: Callable[[str, dict[str, Any]], Any]) -> None:
        self._executors[name] = fn

    def register_scorer(self, name: str, fn: Callable[[Any], float]) -> None:
        self._scorers[name] = fn

    async def execute(self, task: SpeculativeTask, context: dict[str, Any] | None = None) -> SpeculativeResult:
        ctx = context or {}
        candidates = list(task.candidates)

        if not candidates:
            return SpeculativeResult(
                task_id=task.task_id,
                all_candidates=(),
                selection_reason="No candidates provided",
            )

        completed: list[Candidate] = []
        for candidate in candidates:
            result = self._run_candidate(candidate, ctx)
            completed.append(result)

            if task.strategy == SpeculativeStrategy.RACE and result.status == CandidateStatus.COMPLETED:
                break

            if task.strategy == SpeculativeStrategy.CASCADING:
                if result.status == CandidateStatus.COMPLETED and result.quality_score >= task.min_quality_threshold:
                    break

        selected = self._select_best(completed, task.selection, task.min_quality_threshold)
        total_cost = sum(c.cost for c in completed)
        total_latency = max((c.latency_ms for c in completed), default=0.0)

        reason = self._build_reason(selected, task.strategy, task.selection)

        result = SpeculativeResult(
            task_id=task.task_id,
            selected_candidate=selected,
            all_candidates=tuple(completed),
            selection_reason=reason,
            total_cost=total_cost,
            total_latency_ms=total_latency,
            strategy_used=task.strategy,
        )
        self._results.append(result)
        return result

    def get_stats(self) -> dict[str, Any]:
        if not self._results:
            return {"total_executions": 0, "avg_candidates": 0, "selection_rate": 0.0}

        total = len(self._results)
        selected = sum(1 for r in self._results if r.selected_candidate is not None)
        avg_candidates = sum(len(r.all_candidates) for r in self._results) / total

        return {
            "total_executions": total,
            "avg_candidates": avg_candidates,
            "selection_rate": selected / total,
            "total_cost": sum(r.total_cost for r in self._results),
        }

    def _run_candidate(self, candidate: Candidate, context: dict[str, Any]) -> Candidate:
        executor = self._executors.get(candidate.approach_name)
        if not executor:
            return Candidate(
                candidate_id=candidate.candidate_id,
                approach_name=candidate.approach_name,
                agent_id=candidate.agent_id,
                model_id=candidate.model_id,
                status=CandidateStatus.FAILED,
                error=f"No executor for '{candidate.approach_name}'",
            )

        start = time.perf_counter()
        try:
            output = executor(candidate.approach_name, context)
            duration = (time.perf_counter() - start) * 1000

            score = self._score_output(candidate.approach_name, output)

            return Candidate(
                candidate_id=candidate.candidate_id,
                approach_name=candidate.approach_name,
                agent_id=candidate.agent_id,
                model_id=candidate.model_id,
                status=CandidateStatus.COMPLETED,
                output=output,
                quality_score=score,
                cost=candidate.cost,
                latency_ms=duration,
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            return Candidate(
                candidate_id=candidate.candidate_id,
                approach_name=candidate.approach_name,
                agent_id=candidate.agent_id,
                model_id=candidate.model_id,
                status=CandidateStatus.FAILED,
                error=str(e),
                latency_ms=duration,
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )

    def _score_output(self, approach_name: str, output: Any) -> float:
        scorer = self._scorers.get(approach_name)
        if scorer:
            try:
                return scorer(output)
            except Exception:
                return 0.5
        return 0.5

    def _select_best(
        self,
        candidates: list[Candidate],
        criteria: SelectionCriteria,
        min_threshold: float,
    ) -> Candidate | None:
        successful = [c for c in candidates if c.status == CandidateStatus.COMPLETED]
        if not successful:
            return None

        above_threshold = [c for c in successful if c.quality_score >= min_threshold]
        pool = above_threshold if above_threshold else successful

        if criteria == SelectionCriteria.HIGHEST_SCORE:
            return max(pool, key=lambda c: c.quality_score)
        elif criteria == SelectionCriteria.LOWEST_COST:
            return min(pool, key=lambda c: c.cost)
        elif criteria == SelectionCriteria.FASTEST:
            return min(pool, key=lambda c: c.latency_ms)
        elif criteria == SelectionCriteria.MAJORITY_VOTE:
            return self._majority_vote(pool)
        elif criteria == SelectionCriteria.WEIGHTED_ENSEMBLE:
            return max(pool, key=lambda c: c.quality_score * (1.0 / max(c.latency_ms, 1.0)))
        return pool[0] if pool else None

    def _majority_vote(self, candidates: list[Candidate]) -> Candidate | None:
        if not candidates:
            return None
        votes: dict[str, list[Candidate]] = defaultdict(list)
        for c in candidates:
            key = str(c.output)
            votes[key].append(c)
        best_group = max(votes.values(), key=len)
        return max(best_group, key=lambda c: c.quality_score)

    def _build_reason(
        self,
        selected: Candidate | None,
        strategy: SpeculativeStrategy,
        criteria: SelectionCriteria,
    ) -> str:
        if not selected:
            return "No candidate met selection criteria"
        return (
            f"Selected '{selected.approach_name}' via {strategy.value}/{criteria.value} "
            f"(score={selected.quality_score:.2f}, latency={selected.latency_ms:.0f}ms)"
        )
