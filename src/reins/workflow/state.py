"""Node state tracking for multi-node workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class NodeStatus(str, Enum):
    """Status of a workflow node."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass
class NodeState:
    """State of a workflow node."""

    node_id: str
    status: NodeStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    output: dict[str, Any] = field(default_factory=dict)


class NodeStateTracker:
    """Tracks state of workflow nodes."""

    def __init__(self) -> None:
        self.states: dict[str, NodeState] = {}

    def initialize_node(self, node_id: str) -> NodeState:
        """Initialize a node state."""
        state = NodeState(node_id=node_id, status=NodeStatus.PENDING)
        self.states[node_id] = state
        return state

    def start_node(self, node_id: str) -> None:
        """Mark node as running."""
        if node_id in self.states:
            self.states[node_id].status = NodeStatus.RUNNING
            self.states[node_id].started_at = datetime.now(UTC)

    def complete_node(self, node_id: str, output: dict[str, Any] | None = None) -> None:
        """Mark node as completed."""
        if node_id in self.states:
            self.states[node_id].status = NodeStatus.COMPLETED
            self.states[node_id].completed_at = datetime.now(UTC)
            if output:
                self.states[node_id].output = output

    def fail_node(self, node_id: str, error: str) -> None:
        """Mark node as failed."""
        if node_id in self.states:
            self.states[node_id].status = NodeStatus.FAILED
            self.states[node_id].completed_at = datetime.now(UTC)
            self.states[node_id].error = error

    def get_state(self, node_id: str) -> NodeState | None:
        """Get node state."""
        return self.states.get(node_id)

    def is_ready(self, node_id: str, dependencies: list[str]) -> bool:
        """Check if node is ready to run."""
        for dep in dependencies:
            dep_state = self.states.get(dep)
            if not dep_state or dep_state.status != NodeStatus.COMPLETED:
                return False
        return True
