from __future__ import annotations

import heapq
from collections import defaultdict, deque

from reins.topology.types import (
    Bottleneck,
    EdgeKind,
    NodeKind,
    Partition,
    Route,
    TopologyEdge,
    TopologyHealth,
    TopologyNode,
    TopologyStats,
)


class TopologyAnalyzer:
    """Network topology analysis for agent communication graphs.

    Provides graph operations including shortest path routing, partition detection,
    bottleneck identification, and health assessment of agent networks.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, TopologyNode] = {}
        self._edges: dict[str, TopologyEdge] = {}
        self._adjacency: dict[str, list[str]] = defaultdict(list)
        self._reverse_adjacency: dict[str, list[str]] = defaultdict(list)

    def add_node(self, node_id: str, kind: NodeKind = NodeKind.AGENT,
                 label: str = "", capacity: int = 10) -> TopologyNode:
        node = TopologyNode(node_id=node_id, kind=kind, label=label, capacity=capacity)
        self._nodes[node_id] = node
        return node

    def get_node(self, node_id: str) -> TopologyNode | None:
        return self._nodes.get(node_id)

    def remove_node(self, node_id: str) -> bool:
        if node_id not in self._nodes:
            return False
        del self._nodes[node_id]
        edges_to_remove = [
            eid for eid, e in self._edges.items()
            if e.source == node_id or e.target == node_id
        ]
        for eid in edges_to_remove:
            edge = self._edges.pop(eid)
            if edge.target in self._adjacency.get(edge.source, []):
                self._adjacency[edge.source].remove(edge.target)
            if edge.source in self._reverse_adjacency.get(edge.target, []):
                self._reverse_adjacency[edge.target].remove(edge.source)
        return True

    def add_edge(self, source: str, target: str, kind: EdgeKind = EdgeKind.DIRECT,
                 weight: float = 1.0, latency_ms: float = 0.0,
                 bandwidth: float = 1.0) -> TopologyEdge:
        edge = TopologyEdge(
            source=source, target=target, kind=kind,
            weight=weight, latency_ms=latency_ms, bandwidth=bandwidth,
        )
        self._edges[edge.edge_id] = edge
        self._adjacency[source].append(target)
        self._reverse_adjacency[target].append(source)
        if kind == EdgeKind.BIDIRECTIONAL:
            self._adjacency[target].append(source)
            self._reverse_adjacency[source].append(target)
        return edge

    def get_edges(self, source: str | None = None,
                  target: str | None = None) -> list[TopologyEdge]:
        edges = list(self._edges.values())
        if source:
            edges = [e for e in edges if e.source == source]
        if target:
            edges = [e for e in edges if e.target == target]
        return edges

    def get_neighbors(self, node_id: str) -> list[str]:
        return list(self._adjacency.get(node_id, []))

    def get_degree(self, node_id: str) -> int:
        outgoing = len(self._adjacency.get(node_id, []))
        incoming = len(self._reverse_adjacency.get(node_id, []))
        return outgoing + incoming

    def find_shortest_path(self, source: str, target: str) -> Route | None:
        if source not in self._nodes or target not in self._nodes:
            return None
        if source == target:
            return Route(source=source, target=target, path=(source,), total_weight=0.0, hops=0)

        distances: dict[str, float] = {source: 0.0}
        previous: dict[str, str | None] = {source: None}
        heap = [(0.0, source)]

        while heap:
            dist, current = heapq.heappop(heap)
            if current == target:
                break
            if dist > distances.get(current, float("inf")):
                continue
            for neighbor in self._adjacency.get(current, []):
                edge_weight = self._get_edge_weight(current, neighbor)
                new_dist = dist + edge_weight
                if new_dist < distances.get(neighbor, float("inf")):
                    distances[neighbor] = new_dist
                    previous[neighbor] = current
                    heapq.heappush(heap, (new_dist, neighbor))

        if target not in previous:
            return None

        path: list[str] = []
        node = target
        while node is not None:
            path.append(node)
            node = previous.get(node)
        path.reverse()

        return Route(
            source=source,
            target=target,
            path=tuple(path),
            total_weight=distances[target],
            hops=len(path) - 1,
        )

    def detect_partitions(self) -> list[Partition]:
        visited: set[str] = set()
        partitions: list[Partition] = []

        for node_id in self._nodes:
            if node_id in visited:
                continue
            component = self._bfs_component(node_id)
            visited.update(component)
            partitions.append(Partition(
                nodes=tuple(sorted(component)),
                is_isolated=len(component) == 1,
            ))

        return partitions

    def find_bottlenecks(self, top_n: int = 5) -> list[Bottleneck]:
        betweenness = self._compute_betweenness()
        bottlenecks = []
        for node_id in self._nodes:
            node = self._nodes[node_id]
            degree = self.get_degree(node_id)
            load_ratio = node.load / node.capacity if node.capacity > 0 else 0.0
            bottlenecks.append(Bottleneck(
                node_id=node_id,
                degree=degree,
                betweenness=betweenness.get(node_id, 0.0),
                load_ratio=load_ratio,
            ))
        bottlenecks.sort(key=lambda b: b.betweenness, reverse=True)
        return bottlenecks[:top_n]

    def update_load(self, node_id: str, load: int) -> TopologyNode | None:
        node = self._nodes.get(node_id)
        if not node:
            return None
        updated = node.model_copy(update={"load": load})
        self._nodes[node_id] = updated
        return updated

    def get_health(self) -> TopologyHealth:
        if not self._nodes:
            return TopologyHealth.HEALTHY
        partitions = self.detect_partitions()
        if len(partitions) > 1:
            isolated = sum(1 for p in partitions if p.is_isolated)
            if isolated == len(partitions):
                return TopologyHealth.DISCONNECTED
            return TopologyHealth.PARTITIONED

        overloaded = sum(
            1 for n in self._nodes.values()
            if n.capacity > 0 and n.load > n.capacity * 0.8
        )
        if overloaded > len(self._nodes) * 0.3:
            return TopologyHealth.DEGRADED
        return TopologyHealth.HEALTHY

    def get_stats(self) -> TopologyStats:
        by_node_kind: dict[str, int] = defaultdict(int)
        for node in self._nodes.values():
            by_node_kind[node.kind.value] += 1

        by_edge_kind: dict[str, int] = defaultdict(int)
        for edge in self._edges.values():
            by_edge_kind[edge.kind.value] += 1

        total_degree = sum(self.get_degree(nid) for nid in self._nodes)
        avg_degree = total_degree / len(self._nodes) if self._nodes else 0.0

        n = len(self._nodes)
        max_edges = n * (n - 1) if n > 1 else 1
        density = len(self._edges) / max_edges if max_edges > 0 else 0.0

        partitions = self.detect_partitions()

        return TopologyStats(
            total_nodes=len(self._nodes),
            total_edges=len(self._edges),
            partitions=len(partitions),
            avg_degree=avg_degree,
            density=density,
            health=self.get_health(),
            by_node_kind=dict(by_node_kind),
            by_edge_kind=dict(by_edge_kind),
        )

    def _get_edge_weight(self, source: str, target: str) -> float:
        for edge in self._edges.values():
            if edge.source == source and edge.target == target:
                return edge.weight
            if edge.kind == EdgeKind.BIDIRECTIONAL:
                if edge.source == target and edge.target == source:
                    return edge.weight
        return 1.0

    def _bfs_component(self, start: str) -> set[str]:
        visited: set[str] = set()
        queue = deque([start])
        visited.add(start)
        while queue:
            node = queue.popleft()
            for neighbor in self._adjacency.get(node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
            for neighbor in self._reverse_adjacency.get(node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        return visited

    def _compute_betweenness(self) -> dict[str, float]:
        betweenness: dict[str, float] = defaultdict(float)
        nodes = list(self._nodes.keys())

        for source in nodes:
            stack: list[str] = []
            predecessors: dict[str, list[str]] = defaultdict(list)
            sigma: dict[str, int] = defaultdict(int)
            sigma[source] = 1
            dist: dict[str, float] = {source: 0.0}
            queue = deque([source])

            while queue:
                v = queue.popleft()
                stack.append(v)
                for w in self._adjacency.get(v, []):
                    if w not in dist:
                        dist[w] = dist[v] + 1
                        queue.append(w)
                    if dist.get(w, float("inf")) == dist[v] + 1:
                        sigma[w] += sigma[v]
                        predecessors[w].append(v)

            delta: dict[str, float] = defaultdict(float)
            while stack:
                w = stack.pop()
                for v in predecessors[w]:
                    ratio = sigma[v] / sigma[w] if sigma[w] > 0 else 0
                    delta[v] += ratio * (1 + delta[w])
                if w != source:
                    betweenness[w] += delta[w]

        n = len(nodes)
        if n > 2:
            for node in betweenness:
                betweenness[node] /= (n - 1) * (n - 2)

        return dict(betweenness)
