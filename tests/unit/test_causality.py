"""Tests for causal reasoning engine."""

from __future__ import annotations

import pytest

from reins.causality import (
    CausalChain,
    CausalEdge,
    CausalGraph,
    CausalGraphStats,
    CausalNode,
    CausalRelation,
    ConfidenceLevel,
    Counterfactual,
    NodeKind,
    RootCauseResult,
)


@pytest.fixture
def graph() -> CausalGraph:
    return CausalGraph()


def _node(label="action", kind=NodeKind.ACTION, node_id=None):
    kwargs = {"label": label, "kind": kind}
    if node_id:
        kwargs["node_id"] = node_id
    return CausalNode(**kwargs)


def _edge(source_id, target_id, relation=CausalRelation.CAUSES, strength=1.0):
    return CausalEdge(
        source_id=source_id,
        target_id=target_id,
        relation=relation,
        strength=strength,
    )


def test_add_node(graph):
    node = graph.add_node(_node("deploy"))
    assert graph.get_node(node.node_id) is not None
    assert graph.get_node(node.node_id).label == "deploy"


def test_add_edge(graph):
    n1 = graph.add_node(_node("cause"))
    n2 = graph.add_node(_node("effect"))
    edge = graph.add_edge(_edge(n1.node_id, n2.node_id))
    assert graph.get_edge(edge.edge_id) is not None


def test_add_edge_missing_node(graph):
    n1 = graph.add_node(_node("cause"))
    with pytest.raises(ValueError):
        graph.add_edge(_edge(n1.node_id, "nonexistent"))


def test_get_causes(graph):
    n1 = graph.add_node(_node("root"))
    n2 = graph.add_node(_node("middle"))
    n3 = graph.add_node(_node("outcome"))
    graph.add_edge(_edge(n1.node_id, n2.node_id))
    graph.add_edge(_edge(n2.node_id, n3.node_id))

    causes = graph.get_causes(n3.node_id)
    assert len(causes) == 1
    assert causes[0].label == "middle"


def test_get_effects(graph):
    n1 = graph.add_node(_node("action"))
    n2 = graph.add_node(_node("effect1"))
    n3 = graph.add_node(_node("effect2"))
    graph.add_edge(_edge(n1.node_id, n2.node_id))
    graph.add_edge(_edge(n1.node_id, n3.node_id))

    effects = graph.get_effects(n1.node_id)
    assert len(effects) == 2


def test_get_causes_excludes_correlates(graph):
    n1 = graph.add_node(_node("correlated"))
    n2 = graph.add_node(_node("target"))
    graph.add_edge(_edge(n1.node_id, n2.node_id, relation=CausalRelation.CORRELATES))

    causes = graph.get_causes(n2.node_id)
    assert len(causes) == 0


def test_find_root_causes_simple(graph):
    n1 = graph.add_node(_node("root", node_id="root"))
    n2 = graph.add_node(_node("mid", node_id="mid"))
    n3 = graph.add_node(_node("outcome", node_id="outcome"))
    graph.add_edge(_edge("root", "mid"))
    graph.add_edge(_edge("mid", "outcome"))

    result = graph.find_root_causes("outcome")
    assert "root" in result.root_causes
    assert len(result.chains) >= 1


def test_find_root_causes_multiple(graph):
    graph.add_node(_node("r1", node_id="r1"))
    graph.add_node(_node("r2", node_id="r2"))
    graph.add_node(_node("mid", node_id="mid"))
    graph.add_node(_node("out", node_id="out"))
    graph.add_edge(_edge("r1", "mid"))
    graph.add_edge(_edge("r2", "mid"))
    graph.add_edge(_edge("mid", "out"))

    result = graph.find_root_causes("out")
    assert "r1" in result.root_causes
    assert "r2" in result.root_causes


def test_find_root_causes_nonexistent(graph):
    result = graph.find_root_causes("nonexistent")
    assert len(result.root_causes) == 0


def test_find_causal_paths(graph):
    graph.add_node(_node("a", node_id="a"))
    graph.add_node(_node("b", node_id="b"))
    graph.add_node(_node("c", node_id="c"))
    graph.add_edge(_edge("a", "b", strength=0.9))
    graph.add_edge(_edge("b", "c", strength=0.8))

    paths = graph.find_causal_paths("a", "c")
    assert len(paths) == 1
    assert paths[0].total_strength == pytest.approx(0.85)
    assert paths[0].weakest_link == pytest.approx(0.8)


def test_find_causal_paths_multiple(graph):
    graph.add_node(_node("a", node_id="a"))
    graph.add_node(_node("b", node_id="b"))
    graph.add_node(_node("c", node_id="c"))
    graph.add_node(_node("d", node_id="d"))
    graph.add_edge(_edge("a", "b", strength=0.9))
    graph.add_edge(_edge("b", "d", strength=0.8))
    graph.add_edge(_edge("a", "c", strength=0.5))
    graph.add_edge(_edge("c", "d", strength=0.6))

    paths = graph.find_causal_paths("a", "d")
    assert len(paths) == 2
    assert paths[0].total_strength >= paths[1].total_strength


def test_find_causal_paths_no_path(graph):
    graph.add_node(_node("a", node_id="a"))
    graph.add_node(_node("b", node_id="b"))
    paths = graph.find_causal_paths("a", "b")
    assert len(paths) == 0


def test_counterfactual_with_path(graph):
    graph.add_node(_node("deploy", node_id="deploy"))
    graph.add_node(_node("crash", node_id="crash"))
    graph.add_edge(_edge("deploy", "crash", strength=0.9))

    cf = graph.counterfactual("deploy", "crash")
    assert cf.confidence == pytest.approx(0.9)
    assert "deploy" in cf.predicted_outcome.lower() or "Deploy" in cf.predicted_outcome


def test_counterfactual_no_path(graph):
    graph.add_node(_node("a", node_id="a"))
    graph.add_node(_node("b", node_id="b"))

    cf = graph.counterfactual("a", "b")
    assert cf.confidence == 0.0


def test_impact_score_high(graph):
    graph.add_node(_node("root", node_id="root"))
    graph.add_node(_node("a", node_id="a"))
    graph.add_node(_node("b", node_id="b"))
    graph.add_node(_node("c", node_id="c"))
    graph.add_edge(_edge("root", "a"))
    graph.add_edge(_edge("root", "b"))
    graph.add_edge(_edge("b", "c"))

    score = graph.impact_score("root")
    assert score == 1.0


def test_impact_score_leaf(graph):
    graph.add_node(_node("root", node_id="root"))
    graph.add_node(_node("leaf", node_id="leaf"))
    graph.add_edge(_edge("root", "leaf"))

    score = graph.impact_score("leaf")
    assert score == 0.0


def test_impact_score_nonexistent(graph):
    assert graph.impact_score("nope") == 0.0


def test_strengthen_edge(graph):
    graph.add_node(_node("a", node_id="a"))
    graph.add_node(_node("b", node_id="b"))
    edge = graph.add_edge(_edge("a", "b", strength=0.5))

    updated = graph.strengthen_edge(edge.edge_id, 0.2)
    assert updated.strength == pytest.approx(0.7)
    assert updated.evidence_count == 2


def test_strengthen_edge_clamped(graph):
    graph.add_node(_node("a", node_id="a"))
    graph.add_node(_node("b", node_id="b"))
    edge = graph.add_edge(_edge("a", "b", strength=0.95))

    updated = graph.strengthen_edge(edge.edge_id, 0.2)
    assert updated.strength == 1.0


def test_weaken_edge(graph):
    graph.add_node(_node("a", node_id="a"))
    graph.add_node(_node("b", node_id="b"))
    edge = graph.add_edge(_edge("a", "b", strength=0.5))

    updated = graph.weaken_edge(edge.edge_id, 0.2)
    assert updated.strength == pytest.approx(0.3)


def test_weaken_edge_clamped(graph):
    graph.add_node(_node("a", node_id="a"))
    graph.add_node(_node("b", node_id="b"))
    edge = graph.add_edge(_edge("a", "b", strength=0.05))

    updated = graph.weaken_edge(edge.edge_id, 0.2)
    assert updated.strength == 0.0


def test_prune_weak_edges(graph):
    graph.add_node(_node("a", node_id="a"))
    graph.add_node(_node("b", node_id="b"))
    graph.add_node(_node("c", node_id="c"))
    graph.add_edge(_edge("a", "b", strength=0.05))
    graph.add_edge(_edge("a", "c", strength=0.9))

    pruned = graph.prune_weak_edges(threshold=0.1)
    assert pruned == 1
    stats = graph.get_stats()
    assert stats.total_edges == 1


def test_stats_empty(graph):
    stats = graph.get_stats()
    assert stats.total_nodes == 0
    assert stats.total_edges == 0


def test_stats_with_data(graph):
    graph.add_node(_node("a", node_id="a"))
    graph.add_node(_node("b", node_id="b"))
    graph.add_node(_node("c", node_id="c"))
    graph.add_edge(_edge("a", "b", strength=0.8))
    graph.add_edge(_edge("b", "c", strength=0.6))

    stats = graph.get_stats()
    assert stats.total_nodes == 3
    assert stats.total_edges == 2
    assert stats.avg_strength == pytest.approx(0.7)
    assert stats.max_depth == 3
    assert stats.connected_components == 1


def test_stats_disconnected_components(graph):
    graph.add_node(_node("a", node_id="a"))
    graph.add_node(_node("b", node_id="b"))
    graph.add_node(_node("c", node_id="c"))
    graph.add_node(_node("d", node_id="d"))
    graph.add_edge(_edge("a", "b"))
    graph.add_edge(_edge("c", "d"))

    stats = graph.get_stats()
    assert stats.connected_components == 2


def test_enables_relation_counts_as_cause(graph):
    graph.add_node(_node("a", node_id="a"))
    graph.add_node(_node("b", node_id="b"))
    graph.add_edge(_edge("a", "b", relation=CausalRelation.ENABLES))

    causes = graph.get_causes("b")
    assert len(causes) == 1


def test_prevents_relation_not_a_cause(graph):
    graph.add_node(_node("a", node_id="a"))
    graph.add_node(_node("b", node_id="b"))
    graph.add_edge(_edge("a", "b", relation=CausalRelation.PREVENTS))

    causes = graph.get_causes("b")
    assert len(causes) == 0
