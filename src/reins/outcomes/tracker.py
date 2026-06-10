from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import aiofiles  # type: ignore[import-untyped]

from reins.outcomes.types import OutcomeResult, RegressionAlert, utc_now


class OutcomeTracker:
    """Tracks outcome progress over time with JSONL persistence."""

    def __init__(
        self,
        journal_path: Path | str,
        *,
        regression_threshold: float = 0.05,
    ) -> None:
        self.journal_path = Path(journal_path)
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        self.journal_path.touch(exist_ok=True)
        self.regression_threshold = regression_threshold
        self._lock = asyncio.Lock()

    async def record_evaluation(self, result: OutcomeResult) -> None:
        payload = json.dumps(result.model_dump(mode="json"), sort_keys=True) + "\n"
        async with self._lock:
            async with aiofiles.open(self.journal_path, "a", encoding="utf-8") as handle:
                await handle.write(payload)
                await handle.flush()
                await asyncio.to_thread(os.fsync, handle.fileno())

    async def get_progress_history(self, outcome_id: str) -> list[OutcomeResult]:
        results = await self._load_results()
        return [
            result
            for result in sorted(results, key=lambda item: item.evaluated_at)
            if result.outcome_id == outcome_id
        ]

    async def detect_regression(self, outcome_id: str) -> RegressionAlert | None:
        history = await self.get_progress_history(outcome_id)
        if len(history) < 2:
            return None
        previous = history[-2]
        current = history[-1]
        delta = current.overall_score - previous.overall_score
        if delta >= -self.regression_threshold:
            return None
        return RegressionAlert(
            outcome_id=outcome_id,
            previous_score=previous.overall_score,
            current_score=current.overall_score,
            delta=delta,
            threshold=self.regression_threshold,
            previous_result_id=previous.result_id,
            current_result_id=current.result_id,
            evidence={
                "previous_evaluated_at": previous.evaluated_at.isoformat(),
                "current_evaluated_at": current.evaluated_at.isoformat(),
            },
            detected_at=utc_now(),
        )

    async def compute_velocity(self, task_id: str) -> float:
        task_results = [
            result
            for result in await self._load_results()
            if result.evidence.get("task_id") == task_id
        ]
        if len(task_results) < 2:
            return 0.0
        task_results.sort(key=lambda result: result.evaluated_at)
        first = task_results[0]
        latest = task_results[-1]
        elapsed_hours = (latest.evaluated_at - first.evaluated_at).total_seconds() / 3600
        if elapsed_hours <= 0.0:
            return 0.0
        first_passed = self._passed_predicate_ids(first)
        latest_passed = self._passed_predicate_ids(latest)
        newly_satisfied = len(latest_passed - first_passed)
        return newly_satisfied / elapsed_hours

    async def predict_completion(self, outcome_id: str) -> datetime | None:
        history = await self.get_progress_history(outcome_id)
        if len(history) < 2:
            return None
        latest = history[-1]
        velocity = self._score_velocity(history)
        if velocity <= 0.0 or latest.partial_progress >= 1.0:
            return None
        remaining = 1.0 - latest.partial_progress
        hours_remaining = remaining / velocity
        return latest.evaluated_at + timedelta(hours=hours_remaining)

    async def _load_results(self) -> list[OutcomeResult]:
        async with self._lock:
            if not self.journal_path.exists():
                return []
            results: list[OutcomeResult] = []
            async with aiofiles.open(self.journal_path, "r", encoding="utf-8") as handle:
                async for line in handle:
                    if not line.strip():
                        continue
                    results.append(OutcomeResult.model_validate_json(line))
            return results

    @staticmethod
    def _passed_predicate_ids(result: OutcomeResult) -> set[str]:
        return {
            predicate_result.predicate_id
            for predicate_result in result.predicate_results
            if predicate_result.passed
        }

    @staticmethod
    def _score_velocity(history: list[OutcomeResult]) -> float:
        first = history[0]
        latest = history[-1]
        elapsed_hours = (latest.evaluated_at - first.evaluated_at).total_seconds() / 3600
        if elapsed_hours <= 0.0:
            return 0.0
        return max(0.0, latest.partial_progress - first.partial_progress) / elapsed_hours
