from __future__ import annotations

from typing import Any

from reins.intelligence.coordinator import IntelligenceCoordinator


class IntelligenceAdvisor:
    """Concrete RunLifecycleAdvisor backed by IntelligenceCoordinator.

    This lives in the intelligence package and implements the kernel's
    RunLifecycleAdvisor protocol via structural typing (no import needed).
    """

    def __init__(self, coordinator: IntelligenceCoordinator) -> None:
        self._coordinator = coordinator

    async def on_intake(self, objective: str, context: dict[str, Any]) -> dict[str, Any]:
        dag = await self._coordinator.plan_task(objective, context)
        return {
            "dag_proposal": {
                "objective": dag.objective,
                "node_count": len(dag.nodes),
                "nodes": [
                    {"task_id": n.task_id, "description": n.description, "complexity": n.estimated_complexity}
                    for n in dag.nodes
                ],
                "edges": [
                    {"from": e.from_task, "to": e.to_task}
                    for e in dag.edges
                ],
                "has_checkpoints": any(n.requires_checkpoint for n in dag.nodes),
            }
        }

    async def on_before_route(self, state: dict[str, Any]) -> dict[str, Any]:
        recommendation = await self._coordinator.strategy.recommend(state)
        return {
            "strategy": recommendation.strategy,
            "trust_level": recommendation.trust_level.value,
            "requires_approval": recommendation.requires_approval,
            "rationale": recommendation.rationale,
        }

    async def on_after_execution(
        self, task_id: str, domain: str, success: bool, context: dict[str, Any]
    ) -> None:
        severity = context.get("severity", 0.0)
        await self._coordinator.post_completion(task_id, domain, success, severity)

    async def on_repair_required(
        self, failure: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        proposal = await self._coordinator.handle_failure(failure, context)
        return {
            "failure_class": proposal.failure_class,
            "action": proposal.action,
            "rationale": proposal.rationale,
            "requires_approval": proposal.requires_approval,
            "pattern_id": proposal.pattern_id,
            "prior_attempts": proposal.prior_attempts,
            "fallback_classes": list(proposal.fallback_classes),
        }

    async def on_complete(self, task_id: str, domain: str) -> None:
        await self._coordinator.post_completion(task_id, domain, success=True)

    async def on_fail(self, task_id: str, domain: str, reason: str) -> None:
        await self._coordinator.post_completion(task_id, domain, success=False, severity=1.0)
