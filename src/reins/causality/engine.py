from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from reins.causality.types import (
    CausalChain,
    CausalEdge,
    CausalGraphStats,
    CausalNode,
    CausalRelation,
    ConfidenceLevel,
    Counterfactual,
    NodeKind,
    RootCauseResult,
)


class CausalGraph:
    """Tracks causal relationships between agent actions and outcomes.

    Supports root cause analysis, counterfactual reasoning, causal chain
    discovery, and intervention impact prediction.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, CausalNode] = {}
        self._edges: dict[str, CausalEdge] = {}
        self._outgoing: dict[str, list[str]] = defaultdict(list)
        self._incoming: dict[str, list[str]] = defaultdict(list)

    def add_node(self, node: CausalNode) -> CausalNode:
        self._nodes[node.node_id] = node
        return node

    def add_edge(self, edge: CausalEdge) -> CausalEdge:
        if edge.source_id not in self._nodes or edge.target_id not in self._nodes:
            raise ValueError("Both source and target nodes must exist")
        self._edges[edge.edge_id] = edge
        self._outgoing[edge.source_id].append(edge.edge_id)
        self._incoming[edge.target_id].append(edge.edge_id)
        return edge

    def get_node(self, node_id: str) -> CausalNode | None:
        return self._nodes.get(node_id)

    def get_edge(self, edge_id: str) -> CausalEdge | None:
        return self._edges.get(edge_id)

    def get_causes(self, node_id: str) -> list[CausalNode]:
        edge_ids = self._incoming.get(node_id, [])
        causes = []
        for eid in edge_ids:
            edge = self._edges[eid]
            if edge.relation in (CausalRelation.CAUSES, CausalRelation.ENABLES):
                causes.append(self._nodes[edge.source_id])
        return causes

    def get_effects(self, node_id: str) -> list[CausalNode]:
        edge_ids = self._outgoing.get(node_id, [])
        effects = []
        for eid in edge_ids:
            edge = self._edges[eid]
            if edge.relation in (CausalRelation.CAUSES, CausalRelation.ENABLES):
                effects.append(self._nodes[edge.target_id])
        return effects

    def find_root_causes(self, target_id: str, max_depth: int = 10) -> RootCauseResult:
        if target_id not in self._nodes:
            return RootCauseResult(target_node=target_id)

        roots: list[str] = []
        chains: list[CausalChain] = []
        visited: set[str] = set()

        def dfs(current: str, path_nodes: list[str], path_edges: list[str], depth: int) -> None:
            if depth > max_depth or current in visited:
                return
            visited.add(current)

            incoming = self._incoming.get(current, [])
            causal_incoming = [
                eid for eid in incoming
                if self._edges[eid].relation in (CausalRelation.CAUSES, CausalRelation.ENABLES)
            ]

            if not causal_incoming:
                roots.append(current)
                if len(path_nodes) > 1:
                    strengths = [self._edges[eid].strength for eid in path_edges]
                    chains.append(CausalChain(
                        nodes=tuple(path_nodes),
                        edges=tuple(path_edges),
                        total_strength=sum(strengths) / len(strengths) if strengths else 0.0,
                        weakest_link=min(strengths) if strengths else 0.0,
                    ))
                return

            for eid in causal_incoming:
                edge = self._edges[eid]
                new_nodes = [edge.source_id] + path_nodes
                new_edges = [eid] + path_edges
                dfs(edge.source_id, new_nodes, new_edges, depth + 1)

            visited.discard(current)

        dfs(target_id, [target_id], [], 0)

        avg_confidence = 0.0
        if chains:
            avg_confidence = sum(c.total_strength for c in chains) / len(chains)

        return RootCauseResult(
            target_node=target_id,
            root_causes=tuple(dict.fromkeys(roots)),
            chains=tuple(chains),
            confidence=avg_confidence,
        )

    def find_causal_paths(self, source_id: str, target_id: str, max_depth: int = 10) -> list[CausalChain]:
        if source_id not in self._nodes or target_id not in self._nodes:
            return []

        paths: list[CausalChain] = []

        def dfs(current: str, path_nodes: list[str], path_edges: list[str], depth: int) -> None:
            if depth > max_depth:
                return
            if current == target_id:
                strengths = [self._edges[eid].strength for eid in path_edges]
                paths.append(CausalChain(
                    nodes=tuple(path_nodes),
                    edges=tuple(path_edges),
                    total_strength=sum(strengths) / len(strengths) if strengths else 0.0,
                    weakest_link=min(strengths) if strengths else 0.0,
                ))
                return

            for eid in self._outgoing.get(current, []):
                edge = self._edges[eid]
                if edge.target_id not in path_nodes:
                    dfs(
                        edge.target_id,
                        path_nodes + [edge.target_id],
                        path_edges + [eid],
                        depth + 1,
                    )

        dfs(source_id, [source_id], [], 0)
        return sorted(paths, key=lambda p: p.total_strength, reverse=True)

    def counterfactual(self, intervention_node: str, target_node: str) -> Counterfactual:
        paths = self.find_causal_paths(intervention_node, target_node)

        if not paths:
            return Counterfactual(
                intervention_node=intervention_node,
                target_node=target_node,
                confidence=0.0,
            )

        max_strength = max(p.total_strength for p in paths)
        node = self._nodes.get(intervention_node)
        target = self._nodes.get(target_node)

        return Counterfactual(
            intervention_node=intervention_node,
            target_node=target_node,
            original_outcome=target.label if target else "",
            predicted_outcome=f"Without '{node.label if node else intervention_node}', "
                             f"'{target.label if target else target_node}' may not occur",
            confidence=max_strength,
            causal_paths=tuple(paths),
        )

    def impact_score(self, node_id: str) -> float:
        if node_id not in self._nodes:
            return 0.0

        reachable: set[str] = set()
        queue = deque([node_id])
        while queue:
            current = queue.popleft()
            for eid in self._outgoing.get(current, []):
                edge = self._edges[eid]
                if edge.target_id not in reachable:
                    reachable.add(edge.target_id)
                    queue.append(edge.target_id)

        if not self._nodes:
            return 0.0
        return len(reachable) / (len(self._nodes) - 1) if len(self._nodes) > 1 else 0.0

    def strengthen_edge(self, edge_id: str, amount: float = 0.1) -> CausalEdge | None:
        edge = self._edges.get(edge_id)
        if not edge:
            return None
        updated = CausalEdge(
            edge_id=edge.edge_id,
            source_id=edge.source_id,
            target_id=edge.target_id,
            relation=edge.relation,
            strength=min(1.0, edge.strength + amount),
            confidence=edge.confidence,
            evidence_count=edge.evidence_count + 1,
            metadata=edge.metadata,
        )
        self._edges[edge_id] = updated
        return updated

    def weaken_edge(self, edge_id: str, amount: float = 0.1) -> CausalEdge | None:
        edge = self._edges.get(edge_id)
        if not edge:
            return None
        updated = CausalEdge(
            edge_id=edge.edge_id,
            source_id=edge.source_id,
            target_id=edge.target_id,
            relation=edge.relation,
            strength=max(0.0, edge.strength - amount),
            confidence=edge.confidence,
            evidence_count=edge.evidence_count,
            metadata=edge.metadata,
        )
        self._edges[edge_id] = updated
        return updated

    def prune_weak_edges(self, threshold: float = 0.1) -> int:
        to_remove = [eid for eid, e in self._edges.items() if e.strength < threshold]
        for eid in to_remove:
            edge = self._edges.pop(eid)
            self._outgoing[edge.source_id].remove(eid)
            self._incoming[edge.target_id].remove(eid)
        return len(to_remove)

    def get_stats(self) -> CausalGraphStats:
        if not self._nodes:
            return CausalGraphStats()

        avg_strength = 0.0
        if self._edges:
            avg_strength = sum(e.strength for e in self._edges.values()) / len(self._edges)

        max_depth = self._compute_max_depth()
        components = self._count_components()

        return CausalGraphStats(
            total_nodes=len(self._nodes),
            total_edges=len(self._edges),
            avg_strength=avg_strength,
            max_depth=max_depth,
            connected_components=components,
        )

    def _compute_max_depth(self) -> int:
        max_d = 0
        for node_id in self._nodes:
            if not self._incoming.get(node_id):
                depth = self._dfs_depth(node_id, set())
                max_d = max(max_d, depth)
        return max_d

    def _dfs_depth(self, node_id: str, visited: set[str]) -> int:
        if node_id in visited:
            return 0
        visited.add(node_id)
        max_child = 0
        for eid in self._outgoing.get(node_id, []):
            edge = self._edges[eid]
            child_depth = self._dfs_depth(edge.target_id, visited)
            max_child = max(max_child, child_depth)
        visited.discard(node_id)
        return 1 + max_child

    def _count_components(self) -> int:
        visited: set[str] = set()
        components = 0
        for node_id in self._nodes:
            if node_id not in visited:
                components += 1
                queue = deque([node_id])
                while queue:
                    current = queue.popleft()
                    if current in visited:
                        continue
                    visited.add(current)
                    for eid in self._outgoing.get(current, []):
                        queue.append(self._edges[eid].target_id)
                    for eid in self._incoming.get(current, []):
                        queue.append(self._edges[eid].source_id)
        return components
