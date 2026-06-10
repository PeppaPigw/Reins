"""Tests for topology analysis with network graph operations."""

from __future__ import annotations

import pytest

from reins.topology import (
    Bottleneck,
    EdgeKind,
    NodeKind,
    Partition,
    Route,
    TopologyAnalyzer,
    TopologyEdge,
    TopologyHealth,
    TopologyNode,
    TopologyStats,
)


@pytest.fixture
def analyzer() -> TopologyAnalyzer:
    return TopologyAnalyzer()


@pytest.fixture
def linear_graph(analyzer) -> TopologyAnalyzer:
    analyzer.add_node("a")
    analyzer.add_node("b")
    analyzer.add_node("c")
    analyzer.add_edge("a", "b")
    analyzer.add_edge("b", "c")
    return analyzer


@pytest.fixture
def star_graph(analyzer) -> TopologyAnalyzer:
    analyzer.add_node("hub", kind=NodeKind.GATEWAY)
    for i in range(4):
        analyzer.add_node(f"leaf-{i}")
        analyzer.add_edge("hub", f"leaf-{i}", kind=EdgeKind.BIDIRECTIONAL)
    return analyzer


def test_add_node(analyzer):
    node = analyzer.add_node("n1", kind=NodeKind.SERVICE)
    assert node.node_id == "n1"
    assert node.kind == NodeKind.SERVICE


def test_get_node(analyzer):
    analyzer.add_node("n1")
    assert analyzer.get_node("n1") is not None
    assert analyzer.get_node("nonexistent") is None


def test_remove_node(analyzer):
    analyzer.add_node("n1")
    analyzer.add_node("n2")
    analyzer.add_edge("n1", "n2")
    assert analyzer.remove_node("n1") is True
    assert analyzer.get_node("n1") is None
    assert analyzer.get_edges(source="n1") == []


def test_remove_node_not_found(analyzer):
    assert analyzer.remove_node("nonexistent") is False


def test_add_edge(analyzer):
    analyzer.add_node("a")
    analyzer.add_node("b")
    edge = analyzer.add_edge("a", "b", weight=2.5)
    assert edge.source == "a"
    assert edge.target == "b"
    assert edge.weight == 2.5


def test_get_edges_by_source(analyzer):
    analyzer.add_node("a")
    analyzer.add_node("b")
    analyzer.add_node("c")
    analyzer.add_edge("a", "b")
    analyzer.add_edge("a", "c")
    analyzer.add_edge("b", "c")
    edges = analyzer.get_edges(source="a")
    assert len(edges) == 2


def test_get_edges_by_target(analyzer):
    analyzer.add_node("a")
    analyzer.add_node("b")
    analyzer.add_node("c")
    analyzer.add_edge("a", "c")
    analyzer.add_edge("b", "c")
    edges = analyzer.get_edges(target="c")
    assert len(edges) == 2


def test_get_neighbors(linear_graph):
    neighbors = linear_graph.get_neighbors("a")
    assert "b" in neighbors


def test_get_degree(star_graph):
    degree = star_graph.get_degree("hub")
    assert degree >= 4


def test_shortest_path_linear(linear_graph):
    route = linear_graph.find_shortest_path("a", "c")
    assert route is not None
    assert route.path == ("a", "b", "c")
    assert route.hops == 2


def test_shortest_path_same_node(linear_graph):
    route = linear_graph.find_shortest_path("a", "a")
    assert route is not None
    assert route.hops == 0


def test_shortest_path_no_route(analyzer):
    analyzer.add_node("a")
    analyzer.add_node("b")
    route = analyzer.find_shortest_path("a", "b")
    assert route is None


def test_shortest_path_unknown_node(analyzer):
    assert analyzer.find_shortest_path("x", "y") is None


def test_shortest_path_weighted(analyzer):
    analyzer.add_node("a")
    analyzer.add_node("b")
    analyzer.add_node("c")
    analyzer.add_edge("a", "b", weight=10.0)
    analyzer.add_edge("a", "c", weight=1.0)
    analyzer.add_edge("c", "b", weight=1.0)
    route = analyzer.find_shortest_path("a", "b")
    assert route.path == ("a", "c", "b")
    assert route.total_weight == pytest.approx(2.0)


def test_detect_partitions_connected(linear_graph):
    partitions = linear_graph.detect_partitions()
    assert len(partitions) == 1
    assert len(partitions[0].nodes) == 3


def test_detect_partitions_disconnected(analyzer):
    analyzer.add_node("a")
    analyzer.add_node("b")
    analyzer.add_edge("a", "b")
    analyzer.add_node("c")
    analyzer.add_node("d")
    analyzer.add_edge("c", "d")
    partitions = analyzer.detect_partitions()
    assert len(partitions) == 2


def test_detect_partitions_isolated(analyzer):
    analyzer.add_node("a")
    partitions = analyzer.detect_partitions()
    assert len(partitions) == 1
    assert partitions[0].is_isolated is True


def test_find_bottlenecks(star_graph):
    bottlenecks = star_graph.find_bottlenecks(top_n=1)
    assert len(bottlenecks) == 1
    assert bottlenecks[0].node_id == "hub"


def test_find_bottlenecks_linear(linear_graph):
    bottlenecks = linear_graph.find_bottlenecks(top_n=1)
    assert bottlenecks[0].node_id == "b"


def test_update_load(analyzer):
    analyzer.add_node("n1", capacity=10)
    updated = analyzer.update_load("n1", 7)
    assert updated.load == 7


def test_update_load_not_found(analyzer):
    assert analyzer.update_load("nonexistent", 5) is None


def test_health_healthy(linear_graph):
    assert linear_graph.get_health() == TopologyHealth.HEALTHY


def test_health_partitioned(analyzer):
    analyzer.add_node("a")
    analyzer.add_node("b")
    analyzer.add_edge("a", "b")
    analyzer.add_node("c")
    assert analyzer.get_health() == TopologyHealth.PARTITIONED


def test_health_disconnected(analyzer):
    analyzer.add_node("a")
    analyzer.add_node("b")
    analyzer.add_node("c")
    assert analyzer.get_health() == TopologyHealth.DISCONNECTED


def test_health_degraded(analyzer):
    for i in range(5):
        analyzer.add_node(f"n{i}", capacity=10)
    analyzer.add_edge("n0", "n1", kind=EdgeKind.BIDIRECTIONAL)
    analyzer.add_edge("n1", "n2", kind=EdgeKind.BIDIRECTIONAL)
    analyzer.add_edge("n2", "n3", kind=EdgeKind.BIDIRECTIONAL)
    analyzer.add_edge("n3", "n4", kind=EdgeKind.BIDIRECTIONAL)
    for i in range(3):
        analyzer.update_load(f"n{i}", 9)
    assert analyzer.get_health() == TopologyHealth.DEGRADED


def test_stats_empty(analyzer):
    stats = analyzer.get_stats()
    assert stats.total_nodes == 0
    assert stats.total_edges == 0


def test_stats_populated(star_graph):
    stats = star_graph.get_stats()
    assert stats.total_nodes == 5
    assert stats.total_edges == 4
    assert stats.partitions == 1
    assert stats.avg_degree > 0
    assert stats.density > 0
    assert stats.health == TopologyHealth.HEALTHY
    assert "gateway" in stats.by_node_kind


def test_bidirectional_edge_routing(analyzer):
    analyzer.add_node("a")
    analyzer.add_node("b")
    analyzer.add_edge("a", "b", kind=EdgeKind.BIDIRECTIONAL)
    route = analyzer.find_shortest_path("b", "a")
    assert route is not None
    assert route.path == ("b", "a")
