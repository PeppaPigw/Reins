from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from reins.knowledge.types import (
    EdgeKind,
    Inference,
    InferenceKind,
    KnowledgeEdge,
    KnowledgeGraphStats,
    KnowledgeNode,
    NodeKind,
    QueryResult,
)


class KnowledgeGraph:
    """Semantic relationship store for agent reasoning over connected concepts.

    Supports node/edge CRUD, traversal, path finding, transitive inference,
    contradiction detection, and subgraph extraction.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, KnowledgeNode] = {}
        self._edges: dict[str, KnowledgeEdge] = {}
        self._outgoing: dict[str, list[str]] = defaultdict(list)
        self._incoming: dict[str, list[str]] = defaultdict(list)

    def add_node(self, node: KnowledgeNode) -> KnowledgeNode:
        self._nodes[node.node_id] = node
        return node

    def get_node(self, node_id: str) -> KnowledgeNode | None:
        return self._nodes.get(node_id)

    def remove_node(self, node_id: str) -> bool:
        if node_id not in self._nodes:
            return False
        edge_ids_to_remove = []
        for eid in self._outgoing.get(node_id, []):
            edge_ids_to_remove.append(eid)
        for eid in self._incoming.get(node_id, []):
            edge_ids_to_remove.append(eid)
        for eid in set(edge_ids_to_remove):
            self._remove_edge_internal(eid)
        del self._nodes[node_id]
        self._outgoing.pop(node_id, None)
        self._incoming.pop(node_id, None)
        return True

    def add_edge(self, edge: KnowledgeEdge) -> KnowledgeEdge | None:
        if edge.source_id not in self._nodes or edge.target_id not in self._nodes:
            return None
        self._edges[edge.edge_id] = edge
        self._outgoing[edge.source_id].append(edge.edge_id)
        self._incoming[edge.target_id].append(edge.edge_id)
        return edge

    def get_edge(self, edge_id: str) -> KnowledgeEdge | None:
        return self._edges.get(edge_id)

    def remove_edge(self, edge_id: str) -> bool:
        if edge_id not in self._edges:
            return False
        self._remove_edge_internal(edge_id)
        return True

    def get_neighbors(self, node_id: str, edge_kind: EdgeKind | None = None) -> list[KnowledgeNode]:
        neighbors = []
        for eid in self._outgoing.get(node_id, []):
            edge = self._edges.get(eid)
            if edge and (edge_kind is None or edge.kind == edge_kind):
                node = self._nodes.get(edge.target_id)
                if node:
                    neighbors.append(node)
        return neighbors

    def get_predecessors(self, node_id: str, edge_kind: EdgeKind | None = None) -> list[KnowledgeNode]:
        predecessors = []
        for eid in self._incoming.get(node_id, []):
            edge = self._edges.get(eid)
            if edge and (edge_kind is None or edge.kind == edge_kind):
                node = self._nodes.get(edge.source_id)
                if node:
                    predecessors.append(node)
        return predecessors

    def find_path(self, source_id: str, target_id: str) -> list[str] | None:
        if source_id not in self._nodes or target_id not in self._nodes:
            return None
        if source_id == target_id:
            return [source_id]

        visited = {source_id}
        queue: deque[list[str]] = deque([[source_id]])

        while queue:
            path = queue.popleft()
            current = path[-1]
            for eid in self._outgoing.get(current, []):
                edge = self._edges.get(eid)
                if not edge:
                    continue
                next_id = edge.target_id
                if next_id == target_id:
                    return path + [next_id]
                if next_id not in visited:
                    visited.add(next_id)
                    queue.append(path + [next_id])
        return None

    def find_contradictions(self, node_id: str) -> list[tuple[KnowledgeNode, KnowledgeNode]]:
        contradictions = []
        for eid in self._outgoing.get(node_id, []):
            edge = self._edges.get(eid)
            if edge and edge.kind == EdgeKind.CONTRADICTS:
                source = self._nodes.get(edge.source_id)
                target = self._nodes.get(edge.target_id)
                if source and target:
                    contradictions.append((source, target))
        for eid in self._incoming.get(node_id, []):
            edge = self._edges.get(eid)
            if edge and edge.kind == EdgeKind.CONTRADICTS:
                source = self._nodes.get(edge.source_id)
                target = self._nodes.get(edge.target_id)
                if source and target:
                    contradictions.append((source, target))
        return contradictions

    def infer_transitive(self, node_id: str, edge_kind: EdgeKind,
                         max_depth: int = 3) -> list[Inference]:
        inferences = []
        visited = {node_id}
        frontier = [(node_id, [node_id], 1.0)]

        for _ in range(max_depth):
            next_frontier = []
            for current, path, confidence in frontier:
                for eid in self._outgoing.get(current, []):
                    edge = self._edges.get(eid)
                    if not edge or edge.kind != edge_kind:
                        continue
                    target = edge.target_id
                    if target in visited:
                        continue
                    visited.add(target)
                    new_path = path + [target]
                    new_confidence = confidence * edge.weight * 0.9

                    if len(new_path) > 2:
                        inferences.append(Inference(
                            kind=InferenceKind.TRANSITIVE,
                            source_node_id=node_id,
                            target_node_id=target,
                            via_path=tuple(new_path),
                            confidence=new_confidence,
                            explanation=f"Transitive {edge_kind.value} via {len(new_path)-1} hops",
                        ))
                    next_frontier.append((target, new_path, new_confidence))
            frontier = next_frontier

        return inferences

    def query_by_kind(self, node_kind: NodeKind | None = None,
                      edge_kind: EdgeKind | None = None) -> QueryResult:
        nodes = tuple(
            n for n in self._nodes.values()
            if node_kind is None or n.kind == node_kind
        )
        edges = tuple(
            e for e in self._edges.values()
            if edge_kind is None or e.kind == edge_kind
        )
        return QueryResult(nodes=nodes, edges=edges)

    def query_by_label(self, label: str) -> list[KnowledgeNode]:
        return [n for n in self._nodes.values() if label.lower() in n.label.lower()]

    def get_subgraph(self, center_id: str, depth: int = 1) -> QueryResult:
        if center_id not in self._nodes:
            return QueryResult()

        visited_nodes: set[str] = {center_id}
        visited_edges: set[str] = set()
        frontier = {center_id}

        for _ in range(depth):
            next_frontier: set[str] = set()
            for nid in frontier:
                for eid in self._outgoing.get(nid, []):
                    edge = self._edges.get(eid)
                    if edge:
                        visited_edges.add(eid)
                        if edge.target_id not in visited_nodes:
                            visited_nodes.add(edge.target_id)
                            next_frontier.add(edge.target_id)
                for eid in self._incoming.get(nid, []):
                    edge = self._edges.get(eid)
                    if edge:
                        visited_edges.add(eid)
                        if edge.source_id not in visited_nodes:
                            visited_nodes.add(edge.source_id)
                            next_frontier.add(edge.source_id)
            frontier = next_frontier

        nodes = tuple(self._nodes[nid] for nid in visited_nodes if nid in self._nodes)
        edges = tuple(self._edges[eid] for eid in visited_edges if eid in self._edges)
        return QueryResult(nodes=nodes, edges=edges)

    def get_connected_components(self) -> list[set[str]]:
        visited: set[str] = set()
        components: list[set[str]] = []

        for node_id in self._nodes:
            if node_id in visited:
                continue
            component: set[str] = set()
            queue = deque([node_id])
            while queue:
                current = queue.popleft()
                if current in visited:
                    continue
                visited.add(current)
                component.add(current)
                for eid in self._outgoing.get(current, []):
                    edge = self._edges.get(eid)
                    if edge and edge.target_id not in visited:
                        queue.append(edge.target_id)
                for eid in self._incoming.get(current, []):
                    edge = self._edges.get(eid)
                    if edge and edge.source_id not in visited:
                        queue.append(edge.source_id)
            if component:
                components.append(component)

        return components

    def get_stats(self) -> KnowledgeGraphStats:
        node_kinds: dict[str, int] = defaultdict(int)
        for n in self._nodes.values():
            node_kinds[n.kind.value] += 1

        edge_kinds: dict[str, int] = defaultdict(int)
        for e in self._edges.values():
            edge_kinds[e.kind.value] += 1

        total_connections = sum(len(v) for v in self._outgoing.values())
        avg_connections = total_connections / len(self._nodes) if self._nodes else 0.0

        components = self.get_connected_components()

        return KnowledgeGraphStats(
            total_nodes=len(self._nodes),
            total_edges=len(self._edges),
            node_kinds=dict(node_kinds),
            edge_kinds=dict(edge_kinds),
            avg_connections=avg_connections,
            connected_components=len(components),
        )

    def _remove_edge_internal(self, edge_id: str) -> None:
        edge = self._edges.pop(edge_id, None)
        if not edge:
            return
        out_list = self._outgoing.get(edge.source_id, [])
        if edge_id in out_list:
            out_list.remove(edge_id)
        in_list = self._incoming.get(edge.target_id, [])
        if edge_id in in_list:
            in_list.remove(edge_id)
