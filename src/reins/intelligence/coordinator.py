from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from reins.intelligence.types import (
        DAGProposal,
        EscalationDecision,
        MemoryQuery,
        RecoveryProposal,
        ScoredMemory,
        StrategyRecommendation,
        TrustScore,
    )


class Decomposer(Protocol):
    async def decompose(
        self, objective: str, context: dict[str, Any]
    ) -> DAGProposal: ...

    async def restructure(
        self, dag: DAGProposal, failed_task_id: str, failure_context: dict[str, Any]
    ) -> DAGProposal: ...


class MemoryPort(Protocol):
    async def query(self, query: MemoryQuery) -> list[ScoredMemory]: ...
    async def record(self, memory_type: str, content: str, context: dict[str, Any]) -> str: ...
    async def reinforce(self, memory_id: str) -> None: ...


class StrategyPort(Protocol):
    async def recommend(
        self, task_context: dict[str, Any]
    ) -> StrategyRecommendation: ...

    def get_domain_trust(self, domain: str) -> TrustScore: ...
    async def record_outcome(self, domain: str, success: bool, severity: float) -> None: ...


class RecoveryPort(Protocol):
    async def plan_recovery(
        self, failure: dict[str, Any], context: dict[str, Any]
    ) -> RecoveryProposal: ...

    async def record_recovery_outcome(
        self, proposal: RecoveryProposal, success: bool
    ) -> None: ...

    def should_escalate(self, context: dict[str, Any]) -> EscalationDecision: ...


@dataclass
class IntelligenceCoordinator:
    decomposer: Decomposer
    memory: MemoryPort
    strategy: StrategyPort
    recovery: RecoveryPort

    async def plan_task(
        self, objective: str, context: dict[str, Any]
    ) -> DAGProposal:
        from reins.intelligence.types import MemoryQuery

        relevant_memories = await self.memory.query(
            MemoryQuery(query_text=objective, limit=5)
        )
        enriched_context = {
            **context,
            "relevant_memories": [m.record.content for m in relevant_memories],
            "trust": self.strategy.get_domain_trust(
                context.get("domain", "general")
            ),
        }
        return await self.decomposer.decompose(objective, enriched_context)

    async def handle_failure(
        self, failure: dict[str, Any], context: dict[str, Any]
    ) -> RecoveryProposal:
        from reins.intelligence.types import MemoryQuery

        escalation = self.recovery.should_escalate(context)
        if escalation.should_escalate:
            from reins.intelligence.types import RecoveryProposal

            return RecoveryProposal(
                failure_class=context.get("failure_class", "unknown"),
                assumed_failure_class=context.get("failure_class", "unknown"),
                action="escalate_to_human",
                rationale=f"Escalation: {escalation.reason}",
                requires_approval=True,
            )

        past_failures = await self.memory.query(
            MemoryQuery(query_text=str(failure), memory_type=None, limit=5)
        )
        enriched_context = {
            **context,
            "past_failures": [m.record.content for m in past_failures],
        }
        return await self.recovery.plan_recovery(failure, enriched_context)

    async def post_completion(
        self, task_id: str, domain: str, success: bool, severity: float = 0.0
    ) -> None:
        await self.strategy.record_outcome(domain, success, severity)
        if success:
            await self.memory.record(
                memory_type="pattern",
                content=f"Task {task_id} completed successfully",
                context={"task_id": task_id, "domain": domain},
            )
        else:
            await self.memory.record(
                memory_type="failure",
                content=f"Task {task_id} failed (severity={severity})",
                context={"task_id": task_id, "domain": domain, "severity": severity},
            )

    async def restructure_on_failure(
        self, dag: DAGProposal, failed_task_id: str, failure_context: dict[str, Any]
    ) -> DAGProposal:
        return await self.decomposer.restructure(dag, failed_task_id, failure_context)
