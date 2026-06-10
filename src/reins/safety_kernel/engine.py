from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Callable

from reins.safety_kernel.types import (
    GateResult,
    GateStage,
    GateVerdict,
    PipelineResult,
    SafetyKernelStats,
)


class SafetyKernel:
    """Unified safety verification pipeline.

    Chains multiple safety gates (identity, protocol, composability,
    invariants, envelope) into a single evaluation pipeline. Each gate
    can ALLOW, DENY, or ESCALATE. First DENY short-circuits the pipeline.
    """

    def __init__(self) -> None:
        self._gates: dict[GateStage, Callable[[dict[str, Any]], GateVerdict]] = {}
        self._results: list[PipelineResult] = []

    def register_gate(self, stage: GateStage,
                      checker: Callable[[dict[str, Any]], GateVerdict]) -> None:
        self._gates[stage] = checker

    def remove_gate(self, stage: GateStage) -> bool:
        return self._gates.pop(stage, None) is not None

    def evaluate(self, context: dict[str, Any]) -> PipelineResult:
        gates: list[GateResult] = []
        start = time.perf_counter()
        denied_at = None
        final = GateVerdict.ALLOW

        stage_order = [
            GateStage.IDENTITY,
            GateStage.PROTOCOL,
            GateStage.COMPOSABILITY,
            GateStage.INVARIANTS,
            GateStage.ENVELOPE,
        ]

        for stage in stage_order:
            checker = self._gates.get(stage)
            if not checker:
                gates.append(GateResult(
                    stage=stage, verdict=GateVerdict.ALLOW,
                    message="No gate registered (pass-through)",
                ))
                continue

            gate_start = time.perf_counter()
            try:
                verdict = checker(context)
            except Exception as e:
                verdict = GateVerdict.DENY
                gates.append(GateResult(
                    stage=stage, verdict=verdict,
                    message=f"Gate error: {str(e)}",
                    duration_ms=(time.perf_counter() - gate_start) * 1000,
                ))
                denied_at = stage
                final = GateVerdict.DENY
                break

            duration = (time.perf_counter() - gate_start) * 1000
            gates.append(GateResult(
                stage=stage, verdict=verdict,
                message="", duration_ms=duration,
            ))

            if verdict == GateVerdict.DENY:
                denied_at = stage
                final = GateVerdict.DENY
                break
            elif verdict == GateVerdict.ESCALATE:
                final = GateVerdict.ESCALATE

        total_duration = (time.perf_counter() - start) * 1000

        result = PipelineResult(
            final_verdict=final,
            gates=gates,
            total_duration_ms=total_duration,
            denied_at=denied_at,
        )
        self._results.append(result)
        return result

    def evaluate_batch(self, contexts: list[dict[str, Any]]) -> list[PipelineResult]:
        return [self.evaluate(ctx) for ctx in contexts]

    def get_results(self, verdict: GateVerdict | None = None) -> list[PipelineResult]:
        if verdict:
            return [r for r in self._results if r.final_verdict == verdict]
        return list(self._results)

    def get_stats(self) -> SafetyKernelStats:
        if not self._results:
            return SafetyKernelStats()

        allowed = sum(1 for r in self._results if r.final_verdict == GateVerdict.ALLOW)
        denied = sum(1 for r in self._results if r.final_verdict == GateVerdict.DENY)
        escalated = sum(1 for r in self._results if r.final_verdict == GateVerdict.ESCALATE)
        avg_dur = sum(r.total_duration_ms for r in self._results) / len(self._results)

        denial_by_stage: dict[str, int] = defaultdict(int)
        for r in self._results:
            if r.denied_at:
                denial_by_stage[r.denied_at.value] += 1

        return SafetyKernelStats(
            total_evaluations=len(self._results),
            allowed=allowed,
            denied=denied,
            escalated=escalated,
            avg_duration_ms=avg_dur,
            denial_by_stage=dict(denial_by_stage),
        )
