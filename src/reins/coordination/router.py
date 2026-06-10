from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable, Sequence

from reins.coordination.protocol import AgentNode, RoutingStrategy, TaskAssignment


@dataclass(frozen=True)
class RouteScore:
    node: AgentNode
    score: float
    capability_score: float
    trust_score: float
    load_score: float
    success_score: float


class TaskRouter:
    """Scores and selects distributed nodes for task execution."""

    def __init__(self, strategy: RoutingStrategy | str = RoutingStrategy.CAPABILITY_MATCH) -> None:
        self.strategy = RoutingStrategy(strategy)
        self._round_robin_index = 0
        self._history: dict[str, tuple[int, int]] = {}

    async def route_task(
        self,
        nodes: Sequence[AgentNode],
        *,
        task: TaskAssignment,
        strategy: RoutingStrategy | str | None = None,
        excluded_node_ids: Iterable[str] | None = None,
    ) -> AgentNode | None:
        candidates = self._candidate_nodes(nodes, task, excluded_node_ids=excluded_node_ids)
        if not candidates:
            return None

        route_strategy = RoutingStrategy(strategy or self.strategy)
        if route_strategy is RoutingStrategy.ROUND_ROBIN:
            return self._round_robin(candidates)

        scored = await self.score_nodes(candidates, task=task)
        if route_strategy is RoutingStrategy.LEAST_LOADED:
            return min(scored, key=lambda item: (item.node.load_ratio, -item.score)).node
        if route_strategy is RoutingStrategy.TRUST_WEIGHTED:
            return max(scored, key=lambda item: (item.trust_score, item.score)).node
        if route_strategy is RoutingStrategy.AFFINITY:
            return self._affinity_route(scored, task)
        return max(scored, key=lambda item: item.score).node

    async def score_nodes(
        self,
        nodes: Sequence[AgentNode],
        *,
        task: TaskAssignment,
    ) -> list[RouteScore]:
        scores = [await self.score_node(node, task=task) for node in nodes]
        return sorted(scores, key=lambda item: (-item.score, item.node.node_id))

    async def score_node(self, node: AgentNode, *, task: TaskAssignment) -> RouteScore:
        required = set(task.required_capabilities)
        capability_score = (
            1.0
            if not required
            else len(required.intersection(node.capabilities)) / len(required)
        )
        trust_score = node.trust_score
        load_score = 1.0 - min(1.0, node.load_ratio)
        success_score = self._success_rate(node)
        priority_boost = task.priority / 1000
        score = (
            capability_score * 0.45
            + trust_score * 0.25
            + load_score * 0.20
            + success_score * 0.10
            + priority_boost
        )
        return RouteScore(
            node=node,
            score=score,
            capability_score=capability_score,
            trust_score=trust_score,
            load_score=load_score,
            success_score=success_score,
        )

    async def record_result(self, node_id: str, *, success: bool) -> None:
        successes, failures = self._history.get(node_id, (0, 0))
        if success:
            successes += 1
        else:
            failures += 1
        self._history[node_id] = (successes, failures)

    async def fallback_node(
        self,
        nodes: Sequence[AgentNode],
        *,
        failed_node_id: str,
        task: TaskAssignment,
        strategy: RoutingStrategy | str | None = None,
    ) -> AgentNode | None:
        return await self.route_task(
            nodes,
            task=task,
            strategy=strategy,
            excluded_node_ids={failed_node_id},
        )

    def _candidate_nodes(
        self,
        nodes: Sequence[AgentNode],
        task: TaskAssignment,
        *,
        excluded_node_ids: Iterable[str] | None,
    ) -> list[AgentNode]:
        excluded = set(excluded_node_ids or ())
        required = set(task.required_capabilities)
        return [
            node
            for node in nodes
            if node.node_id not in excluded
            and node.is_routable
            and required.issubset(node.capabilities)
        ]

    def _success_rate(self, node: AgentNode) -> float:
        history_successes, history_failures = self._history.get(node.node_id, (0, 0))
        successes = node.completed_tasks + history_successes
        failures = node.failed_tasks + history_failures
        total = successes + failures
        return 0.5 if total == 0 else successes / total

    def _round_robin(self, candidates: Sequence[AgentNode]) -> AgentNode:
        ordered = sorted(candidates, key=lambda node: node.node_id)
        selected = ordered[self._round_robin_index % len(ordered)]
        self._round_robin_index += 1
        return selected

    def _affinity_route(self, scored: Sequence[RouteScore], task: TaskAssignment) -> AgentNode:
        affinity_key = str(task.metadata.get("affinity_key") or task.objective)

        def weighted_score(item: RouteScore) -> tuple[float, float, str]:
            declared = item.node.metadata.get("affinity_key")
            declared_many = item.node.metadata.get("affinity_keys")
            explicit = declared == affinity_key or (
                isinstance(declared_many, list) and affinity_key in declared_many
            )
            digest = hashlib.sha256(
                f"{affinity_key}:{item.node.node_id}".encode("utf-8")
            ).hexdigest()
            stable_weight = int(digest, 16) / ((1 << 256) - 1)
            affinity_score = 1.0 if explicit else stable_weight
            return (
                item.score * 0.75 + affinity_score * 0.25,
                item.score,
                item.node.node_id,
            )

        return max(scored, key=weighted_score).node
