"""Task graph builder for multi-node workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NodeType(str, Enum):
    """Types of workflow nodes."""

    TASK = "task"
    DECISION = "decision"
    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"


@dataclass
class WorkflowNode:
    """A node in the workflow graph."""

    node_id: str
    node_type: NodeType
    name: str
    dependencies: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowGraph:
    """A directed acyclic graph of workflow nodes."""

    graph_id: str
    nodes: dict[str, WorkflowNode] = field(default_factory=dict)
    edges: list[tuple[str, str]] = field(default_factory=list)


class TaskGraphBuilder:
    """Builds task graphs for multi-node workflows."""

    def __init__(self) -> None:
        self.graphs: dict[str, WorkflowGraph] = {}

    def create_graph(self, graph_id: str) -> WorkflowGraph:
        """Create a new workflow graph."""
        graph = WorkflowGraph(graph_id=graph_id)
        self.graphs[graph_id] = graph
        return graph

    def add_node(
        self, graph_id: str, node_id: str, node_type: NodeType, name: str
    ) -> WorkflowNode:
        """Add a node to the graph."""
        graph = self.graphs.get(graph_id)
        if not graph:
            raise ValueError(f"Graph {graph_id} not found")

        node = WorkflowNode(node_id=node_id, node_type=node_type, name=name)
        graph.nodes[node_id] = node
        return node

    def add_edge(self, graph_id: str, from_node: str, to_node: str) -> None:
        """Add an edge between nodes."""
        graph = self.graphs.get(graph_id)
        if not graph:
            raise ValueError(f"Graph {graph_id} not found")

        graph.edges.append((from_node, to_node))

        # Update dependencies
        if to_node in graph.nodes:
            graph.nodes[to_node].dependencies.append(from_node)

    def get_graph(self, graph_id: str) -> WorkflowGraph | None:
        """Get a workflow graph."""
        return self.graphs.get(graph_id)
