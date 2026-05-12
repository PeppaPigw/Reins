from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from reins.intelligence.coordinator import IntelligenceCoordinator
from reins.intelligence.memory.engine import MemoryEngine
from reins.intelligence.recovery.planner import PatternRegistry, RecoveryPlanner
from reins.intelligence.strategy.selector import StrategySelector
from reins.intelligence.strategy.trust import TrustModel
from reins.intelligence.types import (
    DAGEdge,
    DAGProposal,
    MemoryQuery,
    SubtaskNode,
    TrustLevel,
)
from reins.evaluation.classifier import FailureClassifier


class StubDecomposer:
    async def decompose(self, objective: str, context: dict[str, Any]) -> DAGProposal:
        return DAGProposal(
            objective=objective,
            nodes=(
                SubtaskNode(task_id="t1", description="research", estimated_complexity="low", risk_tier="T1"),
                SubtaskNode(task_id="t2", description="implement", estimated_complexity="medium", risk_tier="T2"),
            ),
            edges=(DAGEdge(from_task="t1", to_task="t2"),),
        )

    async def restructure(
        self, dag: DAGProposal, failed_task_id: str, failure_context: dict[str, Any]
    ) -> DAGProposal:
        remaining = tuple(n for n in dag.nodes if n.task_id != failed_task_id)
        return DAGProposal(objective=dag.objective, nodes=remaining, edges=())


@pytest.fixture
def coordinator(tmp_path: Path) -> IntelligenceCoordinator:
    memory = MemoryEngine(tmp_path / "memory")
    trust = TrustModel(tmp_path / "trust")
    strategy = StrategySelector(trust)
    patterns = PatternRegistry(tmp_path / "patterns")
    recovery = RecoveryPlanner(FailureClassifier(), patterns)

    return IntelligenceCoordinator(
        decomposer=StubDecomposer(),
        memory=memory,
        strategy=strategy,
        recovery=recovery,
    )


async def test_plan_task_produces_dag(coordinator: IntelligenceCoordinator) -> None:
    dag = await coordinator.plan_task("Build auth system", {"domain": "backend"})
    assert dag.objective == "Build auth system"
    assert len(dag.nodes) == 2
    assert len(dag.edges) == 1


async def test_handle_failure_returns_proposal(coordinator: IntelligenceCoordinator) -> None:
    proposal = await coordinator.handle_failure(
        failure={"error": "timeout"},
        context={"task_id": "task-1", "domain": "testing"},
    )
    assert proposal.failure_class == "environment_failure"
    assert proposal.action != ""


async def test_post_completion_updates_trust(coordinator: IntelligenceCoordinator) -> None:
    await coordinator.post_completion("task-1", "testing", success=True)
    await coordinator.post_completion("task-2", "testing", success=True)

    trust = coordinator.strategy.get_domain_trust("testing")
    assert trust.effective_successes > 0


async def test_handle_failure_escalates_after_threshold(
    coordinator: IntelligenceCoordinator,
) -> None:
    for i in range(4):
        await coordinator.handle_failure(
            failure={"error": "logic error"},
            context={"task_id": "stuck-task"},
        )

    proposal = await coordinator.handle_failure(
        failure={"error": "logic error"},
        context={"task_id": "stuck-task"},
    )
    assert proposal.action == "escalate_to_human"
