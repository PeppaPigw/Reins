"""Tests for knowledge graph with semantic relationship reasoning."""

from __future__ import annotations

import pytest

from reins.knowledge import (
    EdgeKind,
    Inference,
    InferenceKind,
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeGraphStats,
    KnowledgeNode,
    NodeKind,
    QueryResult,
)


@pytest.fixture
def graph() -> KnowledgeGraph:
    return KnowledgeGraph()


def _node(kind=NodeKind.CONCEPT, label="test"):
    return KnowledgeNode(kind=kind, label=label)


def _edge(source_id, target_id, kind=EdgeKind.RELATED_TO):
    return KnowledgeEdge(source_id=source_id, target_id=target_id, kind=kind)


def test_add_and_get_node(graph):
    node = graph.add_node(_node(label="Python"))
    retrieved = graph.get_node(node.node_id)
    assert retrieved is not None
    assert retrieved.label == "Python"


def test_get_node_not_found(graph):
    assert graph.get_node("nonexistent") is None


def test_remove_node(graph):
    node = graph.add_node(_node())
    assert graph.remove_node(node.node_id)
    assert graph.get_node(node.node_id) is None


def test_remove_node_not_found(graph):
    assert not graph.remove_node("nonexistent")


def test_remove_node_removes_edges(graph):
    a = graph.add_node(_node(label="a"))
    b = graph.add_node(_node(label="b"))
    edge = graph.add_edge(_edge(a.node_id, b.node_id))
    graph.remove_node(a.node_id)
    assert graph.get_edge(edge.edge_id) is None


def test_add_and_get_edge(graph):
    a = graph.add_node(_node(label="a"))
    b = graph.add_node(_node(label="b"))
    edge = graph.add_edge(_edge(a.node_id, b.node_id, EdgeKind.CAUSES))
    assert edge is not None
    retrieved = graph.get_edge(edge.edge_id)
    assert retrieved.kind == EdgeKind.CAUSES


def test_add_edge_missing_node(graph):
    a = graph.add_node(_node(label="a"))
    assert graph.add_edge(_edge(a.node_id, "nonexistent")) is None


def test_remove_edge(graph):
    a = graph.add_node(_node(label="a"))
    b = graph.add_node(_node(label="b"))
    edge = graph.add_edge(_edge(a.node_id, b.node_id))
    assert graph.remove_edge(edge.edge_id)
    assert graph.get_edge(edge.edge_id) is None


def test_remove_edge_not_found(graph):
    assert not graph.remove_edge("nonexistent")


def test_get_neighbors(graph):
    a = graph.add_node(_node(label="a"))
    b = graph.add_node(_node(label="b"))
    c = graph.add_node(_node(label="c"))
    graph.add_edge(_edge(a.node_id, b.node_id))
    graph.add_edge(_edge(a.node_id, c.node_id))
    neighbors = graph.get_neighbors(a.node_id)
    assert len(neighbors) == 2


def test_get_neighbors_filtered(graph):
    a = graph.add_node(_node(label="a"))
    b = graph.add_node(_node(label="b"))
    c = graph.add_node(_node(label="c"))
    graph.add_edge(_edge(a.node_id, b.node_id, EdgeKind.CAUSES))
    graph.add_edge(_edge(a.node_id, c.node_id, EdgeKind.SUPPORTS))
    neighbors = graph.get_neighbors(a.node_id, edge_kind=EdgeKind.CAUSES)
    assert len(neighbors) == 1
    assert neighbors[0].label == "b"


def test_get_predecessors(graph):
    a = graph.add_node(_node(label="a"))
    b = graph.add_node(_node(label="b"))
    graph.add_edge(_edge(a.node_id, b.node_id))
    predecessors = graph.get_predecessors(b.node_id)
    assert len(predecessors) == 1
    assert predecessors[0].label == "a"


def test_find_path(graph):
    a = graph.add_node(_node(label="a"))
    b = graph.add_node(_node(label="b"))
    c = graph.add_node(_node(label="c"))
    graph.add_edge(_edge(a.node_id, b.node_id))
    graph.add_edge(_edge(b.node_id, c.node_id))
    path = graph.find_path(a.node_id, c.node_id)
    assert path == [a.node_id, b.node_id, c.node_id]


def test_find_path_direct(graph):
    a = graph.add_node(_node(label="a"))
    b = graph.add_node(_node(label="b"))
    graph.add_edge(_edge(a.node_id, b.node_id))
    path = graph.find_path(a.node_id, b.node_id)
    assert path == [a.node_id, b.node_id]


def test_find_path_same_node(graph):
    a = graph.add_node(_node(label="a"))
    path = graph.find_path(a.node_id, a.node_id)
    assert path == [a.node_id]


def test_find_path_no_path(graph):
    a = graph.add_node(_node(label="a"))
    b = graph.add_node(_node(label="b"))
    path = graph.find_path(a.node_id, b.node_id)
    assert path is None


def test_find_path_nonexistent_node(graph):
    assert graph.find_path("x", "y") is None


def test_find_contradictions(graph):
    a = graph.add_node(_node(label="a"))
    b = graph.add_node(_node(label="b"))
    graph.add_edge(_edge(a.node_id, b.node_id, EdgeKind.CONTRADICTS))
    contradictions = graph.find_contradictions(a.node_id)
    assert len(contradictions) == 1


def test_find_contradictions_none(graph):
    a = graph.add_node(_node(label="a"))
    b = graph.add_node(_node(label="b"))
    graph.add_edge(_edge(a.node_id, b.node_id, EdgeKind.SUPPORTS))
    contradictions = graph.find_contradictions(a.node_id)
    assert len(contradictions) == 0


def test_infer_transitive(graph):
    a = graph.add_node(_node(label="a"))
    b = graph.add_node(_node(label="b"))
    c = graph.add_node(_node(label="c"))
    graph.add_edge(_edge(a.node_id, b.node_id, EdgeKind.IS_A))
    graph.add_edge(_edge(b.node_id, c.node_id, EdgeKind.IS_A))
    inferences = graph.infer_transitive(a.node_id, EdgeKind.IS_A)
    assert len(inferences) == 1
    assert inferences[0].kind == InferenceKind.TRANSITIVE
    assert inferences[0].target_node_id == c.node_id
    assert inferences[0].confidence > 0


def test_infer_transitive_no_chain(graph):
    a = graph.add_node(_node(label="a"))
    b = graph.add_node(_node(label="b"))
    graph.add_edge(_edge(a.node_id, b.node_id, EdgeKind.IS_A))
    inferences = graph.infer_transitive(a.node_id, EdgeKind.IS_A)
    assert len(inferences) == 0


def test_query_by_node_kind(graph):
    graph.add_node(_node(kind=NodeKind.CONCEPT, label="x"))
    graph.add_node(_node(kind=NodeKind.ENTITY, label="y"))
    result = graph.query_by_kind(node_kind=NodeKind.CONCEPT)
    assert len(result.nodes) == 1
    assert result.nodes[0].label == "x"


def test_query_by_edge_kind(graph):
    a = graph.add_node(_node(label="a"))
    b = graph.add_node(_node(label="b"))
    graph.add_edge(_edge(a.node_id, b.node_id, EdgeKind.CAUSES))
    graph.add_edge(_edge(a.node_id, b.node_id, EdgeKind.SUPPORTS))
    result = graph.query_by_kind(edge_kind=EdgeKind.CAUSES)
    assert len(result.edges) == 1


def test_query_by_label(graph):
    graph.add_node(_node(label="Python Language"))
    graph.add_node(_node(label="Java Language"))
    graph.add_node(_node(label="Rust"))
    results = graph.query_by_label("language")
    assert len(results) == 2


def test_get_subgraph(graph):
    a = graph.add_node(_node(label="center"))
    b = graph.add_node(_node(label="neighbor"))
    c = graph.add_node(_node(label="far"))
    graph.add_edge(_edge(a.node_id, b.node_id))
    graph.add_edge(_edge(b.node_id, c.node_id))
    subgraph = graph.get_subgraph(a.node_id, depth=1)
    assert len(subgraph.nodes) == 2
    assert len(subgraph.edges) == 1


def test_get_subgraph_depth_2(graph):
    a = graph.add_node(_node(label="center"))
    b = graph.add_node(_node(label="neighbor"))
    c = graph.add_node(_node(label="far"))
    graph.add_edge(_edge(a.node_id, b.node_id))
    graph.add_edge(_edge(b.node_id, c.node_id))
    subgraph = graph.get_subgraph(a.node_id, depth=2)
    assert len(subgraph.nodes) == 3


def test_get_subgraph_nonexistent(graph):
    result = graph.get_subgraph("nonexistent")
    assert len(result.nodes) == 0


def test_connected_components_single(graph):
    a = graph.add_node(_node(label="a"))
    b = graph.add_node(_node(label="b"))
    graph.add_edge(_edge(a.node_id, b.node_id))
    components = graph.get_connected_components()
    assert len(components) == 1


def test_connected_components_multiple(graph):
    a = graph.add_node(_node(label="a"))
    b = graph.add_node(_node(label="b"))
    c = graph.add_node(_node(label="c"))
    d = graph.add_node(_node(label="d"))
    graph.add_edge(_edge(a.node_id, b.node_id))
    graph.add_edge(_edge(c.node_id, d.node_id))
    components = graph.get_connected_components()
    assert len(components) == 2


def test_stats_empty():
    g = KnowledgeGraph()
    stats = g.get_stats()
    assert stats.total_nodes == 0
    assert stats.total_edges == 0
    assert stats.connected_components == 0


def test_stats_with_data(graph):
    a = graph.add_node(_node(kind=NodeKind.CONCEPT, label="a"))
    b = graph.add_node(_node(kind=NodeKind.ENTITY, label="b"))
    graph.add_edge(_edge(a.node_id, b.node_id, EdgeKind.CAUSES))
    stats = graph.get_stats()
    assert stats.total_nodes == 2
    assert stats.total_edges == 1
    assert stats.node_kinds["concept"] == 1
    assert stats.edge_kinds["causes"] == 1
    assert stats.avg_connections == 0.5
    assert stats.connected_components == 1
