from __future__ import annotations

from typing import Any

from reins.outcomes.types import (
    GateResult,
    OutcomeSpec,
    PipelineGateResult,
    QualityGate,
    QualityLevel,
    utc_now,
)
from reins.outcomes.verifier import OutcomeVerifier


class QualityGateEngine:
    """Composes multiple outcome specs into quality gates."""

    def __init__(
        self,
        *,
        verifier: OutcomeVerifier | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.verifier = verifier or OutcomeVerifier()
        self.context = context or {}

    async def evaluate_gate(self, gate: QualityGate) -> GateResult:
        outcome_results = [
            await self.verifier.verify(outcome, self.context) for outcome in gate.outcomes
        ]
        overall_score = self._average([result.overall_score for result in outcome_results])
        failed_outcomes = [result.outcome_id for result in outcome_results if not result.passed]
        passed = overall_score >= gate.min_score and not failed_outcomes
        return GateResult(
            gate_id=gate.gate_id,
            name=gate.name,
            quality_level=gate.quality_level,
            passed=passed,
            blocking=gate.blocking,
            overall_score=overall_score,
            min_score=gate.min_score,
            outcome_results=tuple(outcome_results),
            evidence={
                "failed_outcomes": failed_outcomes,
                "outcome_count": len(outcome_results),
            },
            evaluated_at=utc_now(),
        )

    async def evaluate_pipeline_gates(self, gates: list[QualityGate]) -> PipelineGateResult:
        gate_results: list[GateResult] = []
        blocked_by: str | None = None
        for gate in gates:
            result = await self.evaluate_gate(gate)
            gate_results.append(result)
            if gate.blocking and not result.passed:
                blocked_by = gate.name
                break

        overall_score = self._average([result.overall_score for result in gate_results])
        passed = blocked_by is None and all(
            result.passed or not result.blocking for result in gate_results
        )
        return PipelineGateResult(
            passed=passed,
            overall_score=overall_score,
            gate_results=tuple(gate_results),
            blocked_by=blocked_by,
            evidence={"evaluated_gates": len(gate_results), "requested_gates": len(gates)},
            evaluated_at=utc_now(),
        )

    def define_gate(
        self,
        name: str,
        outcomes: tuple[OutcomeSpec, ...] | list[OutcomeSpec],
        min_score: float,
        blocking: bool,
        *,
        quality_level: QualityLevel = QualityLevel.PRE_MERGE,
    ) -> QualityGate:
        return QualityGate(
            name=name,
            outcomes=tuple(outcomes),
            min_score=min_score,
            blocking=blocking,
            quality_level=quality_level,
        )

    @staticmethod
    def pre_commit_gate(outcomes: tuple[OutcomeSpec, ...] | list[OutcomeSpec]) -> QualityGate:
        return QualityGate(
            name="pre-commit",
            outcomes=tuple(outcomes),
            min_score=0.8,
            blocking=True,
            quality_level=QualityLevel.PRE_COMMIT,
        )

    @staticmethod
    def pre_merge_gate(outcomes: tuple[OutcomeSpec, ...] | list[OutcomeSpec]) -> QualityGate:
        return QualityGate(
            name="pre-merge",
            outcomes=tuple(outcomes),
            min_score=0.9,
            blocking=True,
            quality_level=QualityLevel.PRE_MERGE,
        )

    @staticmethod
    def release_gate(outcomes: tuple[OutcomeSpec, ...] | list[OutcomeSpec]) -> QualityGate:
        return QualityGate(
            name="release",
            outcomes=tuple(outcomes),
            min_score=0.95,
            blocking=True,
            quality_level=QualityLevel.RELEASE,
        )

    @staticmethod
    def regression_gate(outcomes: tuple[OutcomeSpec, ...] | list[OutcomeSpec]) -> QualityGate:
        return QualityGate(
            name="regression",
            outcomes=tuple(outcomes),
            min_score=1.0,
            blocking=True,
            quality_level=QualityLevel.REGRESSION,
        )

    @staticmethod
    def _average(values: list[float]) -> float:
        if not values:
            return 0.0
        return max(0.0, min(1.0, sum(values) / len(values)))
