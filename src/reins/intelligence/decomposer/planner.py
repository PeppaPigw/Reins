from __future__ import annotations

from typing import Any, Literal, cast

import ulid

from reins.intelligence.types import (
    Assumption,
    AssumptionStatus,
    DAGEdge,
    DAGProposal,
    SubtaskNode,
)

Complexity = Literal["trivial", "low", "medium", "high", "unknown"]

COMPLEXITY_KEYWORDS: dict[str, list[str]] = {
    "trivial": ["rename", "typo", "comment", "format"],
    "low": ["add field", "update config", "simple test", "log"],
    "medium": ["refactor", "new endpoint", "migration", "integration"],
    "high": ["architecture", "security", "performance", "distributed"],
}

RISK_KEYWORDS: dict[str, list[str]] = {
    "T1": ["test", "docs", "format", "lint", "comment"],
    "T2": ["refactor", "feature", "endpoint", "migration"],
    "T3": ["auth", "security", "deploy", "database schema"],
    "T4": ["production", "data deletion", "infrastructure", "secrets"],
}


class TaskDecomposer:
    def __init__(self, max_depth: int = 3, checkpoint_threshold: float = 0.4) -> None:
        self._max_depth = max_depth
        self._checkpoint_threshold = checkpoint_threshold

    async def decompose(
        self, objective: str, context: dict[str, Any]
    ) -> DAGProposal:
        complexity: Complexity = self._estimate_complexity(objective)
        risk_tier = self._estimate_risk(objective)
        memories = context.get("relevant_memories", [])

        if complexity in ("trivial", "low"):
            node = SubtaskNode(
                task_id=self._gen_id(),
                description=objective,
                estimated_complexity=complexity,
                risk_tier=risk_tier,
            )
            return DAGProposal(objective=objective, nodes=(node,), edges=())

        nodes, edges, assumptions = self._build_dag(objective, complexity, risk_tier, memories)
        return DAGProposal(
            objective=objective,
            nodes=tuple(nodes),
            edges=tuple(edges),
            assumptions=tuple(assumptions),
        )

    async def restructure(
        self, dag: DAGProposal, failed_task_id: str, failure_context: dict[str, Any]
    ) -> DAGProposal:
        remaining_nodes = [n for n in dag.nodes if n.task_id != failed_task_id]
        remaining_edges = [
            e for e in dag.edges
            if e.from_task != failed_task_id and e.to_task != failed_task_id
        ]

        failed_node = next((n for n in dag.nodes if n.task_id == failed_task_id), None)
        if not failed_node:
            return dag

        research_id = self._gen_id()
        retry_id = self._gen_id()

        research_node = SubtaskNode(
            task_id=research_id,
            description=f"Investigate failure in: {failed_node.description}",
            estimated_complexity="low",
            risk_tier="T1",
            requires_checkpoint=True,
        )
        retry_node = SubtaskNode(
            task_id=retry_id,
            description=f"Retry with new approach: {failed_node.description}",
            estimated_complexity=failed_node.estimated_complexity,
            risk_tier=failed_node.risk_tier,
        )

        new_nodes = remaining_nodes + [research_node, retry_node]
        new_edges = remaining_edges + [DAGEdge(from_task=research_id, to_task=retry_id)]

        for edge in dag.edges:
            if edge.to_task == failed_task_id:
                new_edges.append(DAGEdge(from_task=edge.from_task, to_task=research_id))
            if edge.from_task == failed_task_id:
                new_edges.append(DAGEdge(from_task=retry_id, to_task=edge.to_task))

        return DAGProposal(
            objective=dag.objective,
            nodes=tuple(new_nodes),
            edges=tuple(new_edges),
            assumptions=dag.assumptions,
        )

    def _build_dag(
        self,
        objective: str,
        complexity: Complexity,
        risk_tier: str,
        memories: list[str],
    ) -> tuple[list[SubtaskNode], list[DAGEdge], list[Assumption]]:
        nodes: list[SubtaskNode] = []
        edges: list[DAGEdge] = []
        assumptions: list[Assumption] = []

        research_id = self._gen_id()
        implement_id = self._gen_id()
        verify_id = self._gen_id()

        needs_checkpoint = not memories and complexity == "high"

        nodes.append(SubtaskNode(
            task_id=research_id,
            description=f"Research and plan: {objective}",
            estimated_complexity="low",
            risk_tier="T1",
            requires_checkpoint=needs_checkpoint,
        ))
        nodes.append(SubtaskNode(
            task_id=implement_id,
            description=f"Implement: {objective}",
            estimated_complexity=complexity,
            risk_tier=risk_tier,
        ))
        nodes.append(SubtaskNode(
            task_id=verify_id,
            description=f"Verify: {objective}",
            estimated_complexity="low",
            risk_tier="T1",
        ))

        edges.append(DAGEdge(from_task=research_id, to_task=implement_id))
        edges.append(DAGEdge(from_task=implement_id, to_task=verify_id))

        if needs_checkpoint:
            assumptions.append(Assumption(
                assumption_id=self._gen_id(),
                content=f"Approach for '{objective}' is feasible with current codebase",
                source="decomposer_heuristic",
                confidence=self._checkpoint_threshold,
                status=AssumptionStatus.recorded,
            ))

        return nodes, edges, assumptions

    def _estimate_complexity(self, text: str) -> Complexity:
        text_lower = text.lower()
        for level in ("high", "medium", "low", "trivial"):
            if any(kw in text_lower for kw in COMPLEXITY_KEYWORDS[level]):
                return cast(Complexity, level)
        return "medium"

    def _estimate_risk(self, text: str) -> str:
        text_lower = text.lower()
        for tier in ["T4", "T3", "T2", "T1"]:
            if any(kw in text_lower for kw in RISK_KEYWORDS[tier]):
                return tier
        return "T2"

    def _gen_id(self) -> str:
        return str(ulid.new())
