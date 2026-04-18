"""Task metadata and structures for task management system.

Defines TaskMetadata, TaskStatus, and TaskNode (extends WorkflowNode).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from reins.workflow.graph import WorkflowNode, NodeType


class TaskStatus(str, Enum):
    """Status of a task in its lifecycle."""

    PENDING = "pending"
    """Task created but not started"""

    IN_PROGRESS = "in_progress"
    """Task actively being worked on"""

    COMPLETED = "completed"
    """Task finished successfully"""

    ARCHIVED = "archived"
    """Task archived (removed from active view)"""


@dataclass(frozen=True)
class TaskMetadata:
    """Metadata about a task.

    This is the core task data structure used throughout the system.
    """

    task_id: str
    """Unique identifier (e.g., '04-17-implement-auth')"""

    title: str
    """Human-readable title"""

    slug: str
    """URL-friendly slug"""

    task_type: str
    """Type: 'backend', 'frontend', 'fullstack', 'research'"""

    prd_content: str
    """Product Requirements Document (markdown)"""

    acceptance_criteria: list[str]
    """List of acceptance criteria"""

    priority: str
    """Priority: 'P0', 'P1', 'P2', 'P3'"""

    assignee: str
    """Assigned to (agent name or 'unassigned')"""

    status: TaskStatus
    """Current status"""

    branch: str
    """Git branch for this task"""

    base_branch: str
    """Base branch to merge into"""

    created_by: str
    """Who created this task"""

    created_at: datetime
    """When created"""

    started_at: datetime | None = None
    """When started (if in_progress or completed)"""

    completed_at: datetime | None = None
    """When completed (if completed)"""

    parent_task_id: str | None = None
    """Parent task ID if this is a subtask"""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional metadata"""


@dataclass
class TaskNode(WorkflowNode):
    """A workflow node that represents a task.

    Extends WorkflowNode to add task-specific metadata.
    Tasks are first-class workflow nodes, not a separate system.
    """

    task_metadata: TaskMetadata = field(default=None)
    """Task-specific metadata"""

    def __init__(
        self,
        node_id: str,
        name: str,
        task_metadata: TaskMetadata,
        dependencies: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        """Initialize a TaskNode.

        Args:
            node_id: Unique node ID (usually same as task_id)
            name: Node name (usually same as task title)
            task_metadata: Task metadata
            dependencies: List of node IDs this task depends on
            metadata: Additional workflow metadata
        """
        super().__init__(
            node_id=node_id,
            node_type=NodeType.TASK,
            name=name,
            dependencies=dependencies or [],
            metadata=metadata or {},
        )
        self.task_metadata = task_metadata

    @property
    def task_id(self) -> str:
        """Get task ID."""
        return self.task_metadata.task_id

    @property
    def status(self) -> TaskStatus:
        """Get task status."""
        return self.task_metadata.status

    @property
    def is_pending(self) -> bool:
        """Check if task is pending."""
        return self.status == TaskStatus.PENDING

    @property
    def is_in_progress(self) -> bool:
        """Check if task is in progress."""
        return self.status == TaskStatus.IN_PROGRESS

    @property
    def is_completed(self) -> bool:
        """Check if task is completed."""
        return self.status == TaskStatus.COMPLETED

    @property
    def is_archived(self) -> bool:
        """Check if task is archived."""
        return self.status == TaskStatus.ARCHIVED
