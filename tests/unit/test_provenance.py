"""Tests for provenance tracking with integrity verification."""

from __future__ import annotations

import pytest

from reins.provenance import (
    Artifact,
    ArtifactKind,
    IntegrityStatus,
    ProvenanceChain,
    ProvenanceStats,
    ProvenanceTracker,
    Transform,
    TransformKind,
)


@pytest.fixture
def tracker() -> ProvenanceTracker:
    return ProvenanceTracker()


@pytest.fixture
def artifacts(tracker) -> list[Artifact]:
    a1 = tracker.register_artifact(Artifact(
        name="raw_data", kind=ArtifactKind.DATA, checksum="abc123",
    ))
    a2 = tracker.register_artifact(Artifact(
        name="processed", kind=ArtifactKind.INTERMEDIATE, checksum="def456",
    ))
    a3 = tracker.register_artifact(Artifact(
        name="output", kind=ArtifactKind.OUTPUT, checksum="ghi789",
    ))
    tracker.record_transform(
        TransformKind.FILTERING, "agent-1",
        input_ids=[a1.artifact_id], output_ids=[a2.artifact_id],
    )
    tracker.record_transform(
        TransformKind.ENRICHMENT, "agent-2",
        input_ids=[a2.artifact_id], output_ids=[a3.artifact_id],
    )
    return [a1, a2, a3]


def test_register_artifact(tracker):
    a = tracker.register_artifact(Artifact(name="test", kind=ArtifactKind.DATA))
    assert tracker.get_artifact(a.artifact_id) is not None


def test_get_artifact_not_found(tracker):
    assert tracker.get_artifact("nonexistent") is None


def test_record_transform(tracker, artifacts):
    transforms = tracker.get_transforms_for(artifacts[1].artifact_id)
    assert len(transforms) == 1
    assert transforms[0].kind == TransformKind.FILTERING


def test_get_transform(tracker, artifacts):
    transforms = tracker.get_transforms_for(artifacts[1].artifact_id)
    assert tracker.get_transform(transforms[0].transform_id) is not None


def test_get_transform_not_found(tracker):
    assert tracker.get_transform("nonexistent") is None


def test_provenance_chain_depth(tracker, artifacts):
    chain = tracker.get_provenance_chain(artifacts[2].artifact_id)
    assert chain.depth == 2


def test_provenance_chain_origins(tracker, artifacts):
    chain = tracker.get_provenance_chain(artifacts[2].artifact_id)
    assert artifacts[0].artifact_id in chain.origin_artifact_ids


def test_provenance_chain_transforms(tracker, artifacts):
    chain = tracker.get_provenance_chain(artifacts[2].artifact_id)
    assert len(chain.transforms) == 2


def test_provenance_chain_root_artifact(tracker, artifacts):
    chain = tracker.get_provenance_chain(artifacts[0].artifact_id)
    assert chain.depth == 0
    assert artifacts[0].artifact_id in chain.origin_artifact_ids


def test_provenance_chain_missing(tracker):
    chain = tracker.get_provenance_chain("nonexistent")
    assert chain.integrity == IntegrityStatus.MISSING


def test_verify_integrity_verified(tracker):
    a = tracker.register_artifact(Artifact(name="test", checksum="abc123"))
    assert tracker.verify_integrity(a.artifact_id, "abc123") == IntegrityStatus.VERIFIED


def test_verify_integrity_tampered(tracker):
    a = tracker.register_artifact(Artifact(name="test", checksum="abc123"))
    assert tracker.verify_integrity(a.artifact_id, "wrong") == IntegrityStatus.TAMPERED


def test_verify_integrity_unverified(tracker):
    a = tracker.register_artifact(Artifact(name="test", checksum=""))
    assert tracker.verify_integrity(a.artifact_id, "abc") == IntegrityStatus.UNVERIFIED


def test_verify_integrity_missing(tracker):
    assert tracker.verify_integrity("nonexistent", "abc") == IntegrityStatus.MISSING


def test_compute_checksum(tracker):
    cs = tracker.compute_checksum("hello world")
    assert len(cs) == 16
    assert tracker.compute_checksum("hello world") == cs


def test_compute_checksum_different(tracker):
    assert tracker.compute_checksum("a") != tracker.compute_checksum("b")


def test_get_descendants(tracker, artifacts):
    descendants = tracker.get_descendants(artifacts[0].artifact_id)
    assert artifacts[1].artifact_id in descendants
    assert artifacts[2].artifact_id in descendants


def test_get_descendants_leaf(tracker, artifacts):
    descendants = tracker.get_descendants(artifacts[2].artifact_id)
    assert len(descendants) == 0


def test_get_ancestors(tracker, artifacts):
    ancestors = tracker.get_ancestors(artifacts[2].artifact_id)
    assert artifacts[1].artifact_id in ancestors
    assert artifacts[0].artifact_id in ancestors


def test_get_ancestors_root(tracker, artifacts):
    ancestors = tracker.get_ancestors(artifacts[0].artifact_id)
    assert len(ancestors) == 0


def test_stats_empty():
    t = ProvenanceTracker()
    stats = t.get_stats()
    assert stats.total_artifacts == 0
    assert stats.total_transforms == 0


def test_stats_with_data(tracker, artifacts):
    stats = tracker.get_stats()
    assert stats.total_artifacts == 3
    assert stats.total_transforms == 2
    assert stats.agents_involved == 2
    assert ArtifactKind.DATA.value in stats.by_kind
    assert stats.avg_chain_depth > 0
