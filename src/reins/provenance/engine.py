from __future__ import annotations

import hashlib
from collections import defaultdict

from reins.provenance.types import (
    Artifact,
    ArtifactKind,
    IntegrityStatus,
    ProvenanceChain,
    ProvenanceStats,
    Transform,
    TransformKind,
)


class ProvenanceTracker:
    """Tracks origin and transformation history of every artifact.

    Builds directed acyclic graphs of data lineage, verifies integrity
    through checksum chains, and detects tampering.
    """

    def __init__(self) -> None:
        self._artifacts: dict[str, Artifact] = {}
        self._transforms: dict[str, Transform] = {}
        self._artifact_transforms: dict[str, list[str]] = defaultdict(list)

    def register_artifact(self, artifact: Artifact) -> Artifact:
        self._artifacts[artifact.artifact_id] = artifact
        return artifact

    def get_artifact(self, artifact_id: str) -> Artifact | None:
        return self._artifacts.get(artifact_id)

    def record_transform(self, kind: TransformKind, agent_id: str,
                         input_ids: list[str], output_ids: list[str],
                         description: str = "",
                         metadata: dict | None = None) -> Transform:
        transform = Transform(
            kind=kind,
            agent_id=agent_id,
            input_ids=tuple(input_ids),
            output_ids=tuple(output_ids),
            description=description,
            metadata=metadata or {},
        )
        self._transforms[transform.transform_id] = transform
        for oid in output_ids:
            self._artifact_transforms[oid].append(transform.transform_id)
        return transform

    def get_transform(self, transform_id: str) -> Transform | None:
        return self._transforms.get(transform_id)

    def get_provenance_chain(self, artifact_id: str) -> ProvenanceChain:
        if artifact_id not in self._artifacts:
            return ProvenanceChain(artifact_id=artifact_id, integrity=IntegrityStatus.MISSING)

        visited_transforms: list[str] = []
        origins: set[str] = set()
        self._trace_back(artifact_id, visited_transforms, origins, set())

        depth = len(visited_transforms)
        integrity = self._verify_chain_integrity(artifact_id, visited_transforms)

        return ProvenanceChain(
            artifact_id=artifact_id,
            transforms=tuple(visited_transforms),
            origin_artifact_ids=tuple(origins),
            depth=depth,
            integrity=integrity,
        )

    def verify_integrity(self, artifact_id: str, expected_checksum: str) -> IntegrityStatus:
        artifact = self._artifacts.get(artifact_id)
        if not artifact:
            return IntegrityStatus.MISSING
        if not artifact.checksum:
            return IntegrityStatus.UNVERIFIED
        if artifact.checksum == expected_checksum:
            return IntegrityStatus.VERIFIED
        return IntegrityStatus.TAMPERED

    def compute_checksum(self, content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def get_descendants(self, artifact_id: str) -> list[str]:
        descendants: list[str] = []
        visited: set[str] = set()
        self._trace_forward(artifact_id, descendants, visited)
        return descendants

    def get_ancestors(self, artifact_id: str) -> list[str]:
        ancestors: list[str] = []
        visited: set[str] = set()
        self._collect_ancestors(artifact_id, ancestors, visited)
        return ancestors

    def get_transforms_for(self, artifact_id: str) -> list[Transform]:
        transform_ids = self._artifact_transforms.get(artifact_id, [])
        return [self._transforms[tid] for tid in transform_ids if tid in self._transforms]

    def get_stats(self) -> ProvenanceStats:
        agents = set()
        for t in self._transforms.values():
            agents.add(t.agent_id)

        by_kind: dict[str, int] = defaultdict(int)
        for a in self._artifacts.values():
            by_kind[a.kind.value] += 1

        by_integrity: dict[str, int] = defaultdict(int)
        for aid in self._artifacts:
            chain = self.get_provenance_chain(aid)
            by_integrity[chain.integrity.value] += 1

        depths = []
        for aid in self._artifacts:
            chain = self.get_provenance_chain(aid)
            depths.append(chain.depth)
        avg_depth = sum(depths) / len(depths) if depths else 0.0

        return ProvenanceStats(
            total_artifacts=len(self._artifacts),
            total_transforms=len(self._transforms),
            avg_chain_depth=avg_depth,
            by_kind=dict(by_kind),
            by_integrity=dict(by_integrity),
            agents_involved=len(agents),
        )

    def _trace_back(self, artifact_id: str, transforms: list[str],
                    origins: set[str], visited: set[str]) -> None:
        if artifact_id in visited:
            return
        visited.add(artifact_id)

        transform_ids = self._artifact_transforms.get(artifact_id, [])
        if not transform_ids:
            origins.add(artifact_id)
            return

        for tid in transform_ids:
            transform = self._transforms.get(tid)
            if transform and tid not in transforms:
                transforms.append(tid)
                for input_id in transform.input_ids:
                    self._trace_back(input_id, transforms, origins, visited)

    def _trace_forward(self, artifact_id: str, descendants: list[str],
                       visited: set[str]) -> None:
        if artifact_id in visited:
            return
        visited.add(artifact_id)

        for transform in self._transforms.values():
            if artifact_id in transform.input_ids:
                for oid in transform.output_ids:
                    if oid not in visited:
                        descendants.append(oid)
                        self._trace_forward(oid, descendants, visited)

    def _collect_ancestors(self, artifact_id: str, ancestors: list[str],
                           visited: set[str]) -> None:
        if artifact_id in visited:
            return
        visited.add(artifact_id)

        transform_ids = self._artifact_transforms.get(artifact_id, [])
        for tid in transform_ids:
            transform = self._transforms.get(tid)
            if transform:
                for input_id in transform.input_ids:
                    if input_id not in visited:
                        ancestors.append(input_id)
                        self._collect_ancestors(input_id, ancestors, visited)

    def _verify_chain_integrity(self, artifact_id: str,
                                transform_ids: list[str]) -> IntegrityStatus:
        artifact = self._artifacts.get(artifact_id)
        if not artifact:
            return IntegrityStatus.MISSING
        if not artifact.checksum:
            return IntegrityStatus.UNVERIFIED
        return IntegrityStatus.VERIFIED
