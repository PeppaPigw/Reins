from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from reins.lineage.types import (
    Artifact,
    ArtifactKind,
    LineageEdge,
    LineageQuery,
    LineageRelation,
    LineageStats,
    ProvenanceChain,
)


class LineageTracker:
    """Full provenance tracking for every agent output.

    Records artifacts and their derivation relationships, enabling
    audit trails, reproducibility verification, and impact analysis.
    """

    def __init__(self) -> None:
        self._artifacts: dict[str, Artifact] = {}
        self._edges: dict[str, LineageEdge] = {}
        self._outgoing: dict[str, list[str]] = defaultdict(list)
        self._incoming: dict[str, list[str]] = defaultdict(list)

    def record_artifact(self, artifact: Artifact) -> Artifact:
        self._artifacts[artifact.artifact_id] = artifact
        return artifact

    def record_derivation(self, source_id: str, target_id: str,
                          relation: LineageRelation = LineageRelation.DERIVED_FROM,
                          metadata: dict[str, Any] | None = None) -> LineageEdge | None:
        if source_id not in self._artifacts or target_id not in self._artifacts:
            return None
        edge = LineageEdge(
            source_id=source_id,
            target_id=target_id,
            relation=relation,
            metadata=metadata or {},
        )
        self._edges[edge.edge_id] = edge
        self._outgoing[source_id].append(edge.edge_id)
        self._incoming[target_id].append(edge.edge_id)
        return edge

    def get_artifact(self, artifact_id: str) -> Artifact | None:
        return self._artifacts.get(artifact_id)

    def get_provenance(self, artifact_id: str, max_depth: int = 10) -> ProvenanceChain:
        if artifact_id not in self._artifacts:
            return ProvenanceChain(artifact_id=artifact_id, complete=False)

        ancestors: list[str] = []
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(artifact_id, 0)])
        max_d = 0

        while queue:
            current, depth = queue.popleft()
            if depth > max_depth:
                continue
            max_d = max(max_d, depth)

            for eid in self._incoming.get(current, []):
                edge = self._edges[eid]
                if edge.source_id not in visited:
                    visited.add(edge.source_id)
                    ancestors.append(edge.source_id)
                    queue.append((edge.source_id, depth + 1))

        return ProvenanceChain(
            artifact_id=artifact_id,
            ancestors=tuple(ancestors),
            depth=max_d,
            complete=True,
        )

    def get_descendants(self, artifact_id: str, max_depth: int = 10) -> list[str]:
        if artifact_id not in self._artifacts:
            return []

        descendants: list[str] = []
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(artifact_id, 0)])

        while queue:
            current, depth = queue.popleft()
            if depth > max_depth:
                continue
            for eid in self._outgoing.get(current, []):
                edge = self._edges[eid]
                if edge.target_id not in visited:
                    visited.add(edge.target_id)
                    descendants.append(edge.target_id)
                    queue.append((edge.target_id, depth + 1))

        return descendants

    def query(self, q: LineageQuery) -> list[Artifact]:
        pool = list(self._artifacts.values())

        if q.agent_id:
            pool = [a for a in pool if a.agent_id == q.agent_id]
        if q.run_id:
            pool = [a for a in pool if a.run_id == q.run_id]
        if q.kind:
            pool = [a for a in pool if a.kind == q.kind]

        if q.artifact_id:
            if q.direction == "ancestors":
                chain = self.get_provenance(q.artifact_id, q.max_depth)
                ids = set(chain.ancestors)
                pool = [a for a in pool if a.artifact_id in ids]
            else:
                desc = self.get_descendants(q.artifact_id, q.max_depth)
                ids = set(desc)
                pool = [a for a in pool if a.artifact_id in ids]

        return pool

    def verify_integrity(self, artifact_id: str) -> bool:
        if artifact_id not in self._artifacts:
            return False
        chain = self.get_provenance(artifact_id)
        for ancestor_id in chain.ancestors:
            if ancestor_id not in self._artifacts:
                return False
        return True

    def find_orphans(self) -> list[Artifact]:
        return [
            a for a in self._artifacts.values()
            if not self._incoming.get(a.artifact_id) and not self._outgoing.get(a.artifact_id)
        ]

    def impact_analysis(self, artifact_id: str) -> dict[str, Any]:
        descendants = self.get_descendants(artifact_id)
        by_kind: dict[str, int] = defaultdict(int)
        for did in descendants:
            art = self._artifacts.get(did)
            if art:
                by_kind[art.kind.value] += 1

        return {
            "artifact_id": artifact_id,
            "total_descendants": len(descendants),
            "by_kind": dict(by_kind),
            "direct_dependents": len(self._outgoing.get(artifact_id, [])),
        }

    def get_stats(self) -> LineageStats:
        if not self._artifacts:
            return LineageStats()

        by_kind: dict[str, int] = defaultdict(int)
        for a in self._artifacts.values():
            by_kind[a.kind.value] += 1

        by_relation: dict[str, int] = defaultdict(int)
        for e in self._edges.values():
            by_relation[e.relation.value] += 1

        max_depth = 0
        for aid in self._artifacts:
            if not self._incoming.get(aid):
                depth = self._compute_depth(aid)
                max_depth = max(max_depth, depth)

        orphans = self.find_orphans()

        return LineageStats(
            total_artifacts=len(self._artifacts),
            total_edges=len(self._edges),
            by_kind=dict(by_kind),
            by_relation=dict(by_relation),
            max_chain_depth=max_depth,
            orphan_count=len(orphans),
        )

    def _compute_depth(self, node_id: str) -> int:
        max_child = 0
        for eid in self._outgoing.get(node_id, []):
            edge = self._edges[eid]
            child_depth = self._compute_depth(edge.target_id)
            max_child = max(max_child, child_depth)
        return 1 + max_child if self._outgoing.get(node_id) else 1
