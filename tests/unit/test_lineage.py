"""Tests for execution lineage tracker."""

from __future__ import annotations

import pytest

from reins.lineage import (
    Artifact,
    ArtifactKind,
    LineageEdge,
    LineageQuery,
    LineageRelation,
    LineageStats,
    LineageTracker,
    ProvenanceChain,
)


@pytest.fixture
def tracker() -> LineageTracker:
    return LineageTracker()


def _artifact(kind=ArtifactKind.CODE, agent_id="agent-1", run_id="run-1",
              description="test", artifact_id=None):
    kwargs = {"kind": kind, "agent_id": agent_id, "run_id": run_id, "description": description}
    if artifact_id:
        kwargs["artifact_id"] = artifact_id
    return Artifact(**kwargs)


def test_record_and_get_artifact(tracker):
    art = tracker.record_artifact(_artifact(description="hello"))
    retrieved = tracker.get_artifact(art.artifact_id)
    assert retrieved is not None
    assert retrieved.description == "hello"


def test_get_nonexistent_artifact(tracker):
    assert tracker.get_artifact("nonexistent") is None


def test_record_derivation(tracker):
    a1 = tracker.record_artifact(_artifact(artifact_id="a1"))
    a2 = tracker.record_artifact(_artifact(artifact_id="a2"))
    edge = tracker.record_derivation("a1", "a2")
    assert edge is not None
    assert edge.source_id == "a1"
    assert edge.target_id == "a2"


def test_record_derivation_missing_node(tracker):
    tracker.record_artifact(_artifact(artifact_id="a1"))
    assert tracker.record_derivation("a1", "nonexistent") is None


def test_get_provenance_simple(tracker):
    tracker.record_artifact(_artifact(artifact_id="root"))
    tracker.record_artifact(_artifact(artifact_id="mid"))
    tracker.record_artifact(_artifact(artifact_id="leaf"))
    tracker.record_derivation("root", "mid")
    tracker.record_derivation("mid", "leaf")

    chain = tracker.get_provenance("leaf")
    assert "mid" in chain.ancestors
    assert "root" in chain.ancestors
    assert chain.complete


def test_get_provenance_nonexistent(tracker):
    chain = tracker.get_provenance("nonexistent")
    assert not chain.complete


def test_get_descendants(tracker):
    tracker.record_artifact(_artifact(artifact_id="root"))
    tracker.record_artifact(_artifact(artifact_id="child1"))
    tracker.record_artifact(_artifact(artifact_id="child2"))
    tracker.record_artifact(_artifact(artifact_id="grandchild"))
    tracker.record_derivation("root", "child1")
    tracker.record_derivation("root", "child2")
    tracker.record_derivation("child1", "grandchild")

    desc = tracker.get_descendants("root")
    assert len(desc) == 3
    assert "child1" in desc
    assert "child2" in desc
    assert "grandchild" in desc


def test_get_descendants_nonexistent(tracker):
    assert tracker.get_descendants("nonexistent") == []


def test_query_by_agent(tracker):
    tracker.record_artifact(_artifact(agent_id="a"))
    tracker.record_artifact(_artifact(agent_id="b"))
    tracker.record_artifact(_artifact(agent_id="a"))

    results = tracker.query(LineageQuery(agent_id="a"))
    assert len(results) == 2


def test_query_by_run(tracker):
    tracker.record_artifact(_artifact(run_id="r1"))
    tracker.record_artifact(_artifact(run_id="r2"))

    results = tracker.query(LineageQuery(run_id="r1"))
    assert len(results) == 1


def test_query_by_kind(tracker):
    tracker.record_artifact(_artifact(kind=ArtifactKind.CODE))
    tracker.record_artifact(_artifact(kind=ArtifactKind.DECISION))
    tracker.record_artifact(_artifact(kind=ArtifactKind.CODE))

    results = tracker.query(LineageQuery(kind=ArtifactKind.CODE))
    assert len(results) == 2


def test_query_ancestors(tracker):
    tracker.record_artifact(_artifact(artifact_id="root", kind=ArtifactKind.PROMPT))
    tracker.record_artifact(_artifact(artifact_id="mid", kind=ArtifactKind.RESPONSE))
    tracker.record_artifact(_artifact(artifact_id="leaf", kind=ArtifactKind.CODE))
    tracker.record_derivation("root", "mid")
    tracker.record_derivation("mid", "leaf")

    results = tracker.query(LineageQuery(artifact_id="leaf", direction="ancestors"))
    assert len(results) == 2


def test_query_descendants(tracker):
    tracker.record_artifact(_artifact(artifact_id="root"))
    tracker.record_artifact(_artifact(artifact_id="child"))
    tracker.record_derivation("root", "child")

    results = tracker.query(LineageQuery(artifact_id="root", direction="descendants"))
    assert len(results) == 1


def test_verify_integrity_valid(tracker):
    tracker.record_artifact(_artifact(artifact_id="a"))
    tracker.record_artifact(_artifact(artifact_id="b"))
    tracker.record_derivation("a", "b")

    assert tracker.verify_integrity("b")


def test_verify_integrity_nonexistent(tracker):
    assert not tracker.verify_integrity("nonexistent")


def test_find_orphans(tracker):
    tracker.record_artifact(_artifact(artifact_id="connected1"))
    tracker.record_artifact(_artifact(artifact_id="connected2"))
    tracker.record_artifact(_artifact(artifact_id="orphan"))
    tracker.record_derivation("connected1", "connected2")

    orphans = tracker.find_orphans()
    assert len(orphans) == 1
    assert orphans[0].artifact_id == "orphan"


def test_impact_analysis(tracker):
    tracker.record_artifact(_artifact(artifact_id="root"))
    tracker.record_artifact(_artifact(artifact_id="c1", kind=ArtifactKind.CODE))
    tracker.record_artifact(_artifact(artifact_id="c2", kind=ArtifactKind.TEST_RESULT))
    tracker.record_artifact(_artifact(artifact_id="c3", kind=ArtifactKind.CODE))
    tracker.record_derivation("root", "c1")
    tracker.record_derivation("root", "c2")
    tracker.record_derivation("c1", "c3")

    impact = tracker.impact_analysis("root")
    assert impact["total_descendants"] == 3
    assert impact["direct_dependents"] == 2
    assert impact["by_kind"]["code"] == 2


def test_impact_analysis_leaf(tracker):
    tracker.record_artifact(_artifact(artifact_id="leaf"))
    impact = tracker.impact_analysis("leaf")
    assert impact["total_descendants"] == 0


def test_stats_empty(tracker):
    stats = tracker.get_stats()
    assert stats.total_artifacts == 0
    assert stats.total_edges == 0


def test_stats_with_data(tracker):
    tracker.record_artifact(_artifact(artifact_id="a", kind=ArtifactKind.PROMPT))
    tracker.record_artifact(_artifact(artifact_id="b", kind=ArtifactKind.CODE))
    tracker.record_artifact(_artifact(artifact_id="c", kind=ArtifactKind.CODE))
    tracker.record_derivation("a", "b", LineageRelation.DERIVED_FROM)
    tracker.record_derivation("b", "c", LineageRelation.TRIGGERED_BY)

    stats = tracker.get_stats()
    assert stats.total_artifacts == 3
    assert stats.total_edges == 2
    assert stats.by_kind["code"] == 2
    assert stats.by_kind["prompt"] == 1
    assert stats.by_relation["derived_from"] == 1
    assert stats.by_relation["triggered_by"] == 1
    assert stats.max_chain_depth >= 2


def test_stats_orphan_count(tracker):
    tracker.record_artifact(_artifact(artifact_id="orphan1"))
    tracker.record_artifact(_artifact(artifact_id="orphan2"))
    stats = tracker.get_stats()
    assert stats.orphan_count == 2


def test_multiple_relations(tracker):
    tracker.record_artifact(_artifact(artifact_id="code"))
    tracker.record_artifact(_artifact(artifact_id="test"))
    tracker.record_artifact(_artifact(artifact_id="approval"))
    tracker.record_derivation("code", "test", LineageRelation.VALIDATED_BY)
    tracker.record_derivation("code", "approval", LineageRelation.APPROVED_BY)

    desc = tracker.get_descendants("code")
    assert len(desc) == 2


def test_max_depth_limit(tracker):
    prev = "n0"
    tracker.record_artifact(_artifact(artifact_id="n0"))
    for i in range(1, 20):
        nid = f"n{i}"
        tracker.record_artifact(_artifact(artifact_id=nid))
        tracker.record_derivation(prev, nid)
        prev = nid

    chain = tracker.get_provenance("n19", max_depth=5)
    assert len(chain.ancestors) <= 6
