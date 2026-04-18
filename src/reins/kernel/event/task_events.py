"""Task-related event types for task management system.

Events emitted when tasks are created, started, completed, or archived.
These events are the source of truth for the TaskContextProjection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class TaskCreatedEvent:
    """Event emitted when a task is created.

    This is the primary event for adding new tasks to the system.
    """

    task_id: str
    """Unique identifier for this task (e.g., '04-17-implement-auth')"""

    title: str
    """Human-readable task title"""

    slug: str
    """URL-friendly slug derived from title"""

    task_type: str
    """Type of task: 'backend', 'frontend', 'fullstack', 'research', etc."""

    prd_content: str
    """Product Requirements Document content (markdown)"""

    acceptance_criteria: list[str]
    """List of acceptance criteria that must be met"""

    priority: str
    """Priority level: 'P0' (critical), 'P1' (high), 'P2' (medium), 'P3' (low)"""

    assignee: str
    """Who is assigned to this task (agent name or 'unassigned')"""

    branch: str
    """Git branch for this task (e.g., 'feat/implement-auth')"""

    base_branch: str
    """Base branch to merge into (usually 'main')"""

    created_by: str
    """Who created this task ('user', 'system', 'agent')"""

    created_at: datetime
    """When the task was created"""

    parent_task_id: str | None = None
    """Parent task ID if this is a subtask"""

    metadata: dict[str, Any] | None = None
    """Additional metadata (package, estimated_hours, etc.)"""


@dataclass(frozen=True)
class TaskStartedEvent:
    """Event emitted when a task is started.

    Marks the transition from 'pending' to 'in_progress'.
    """

    task_id: str
    """ID of the task being started"""

    assignee: str
    """Who is starting this task"""

    started_at: datetime
    """When the task was started"""


@dataclass(frozen=True)
class TaskCompletedEvent:
    """Event emitted when a task is completed.

    Marks the transition from 'in_progress' to 'completed'.
    """

    task_id: str
    """ID of the task being completed"""

    completed_at: datetime
    """When the task was completed"""

    outcome: dict[str, Any]
    """Outcome data (files_modified, tests_added, etc.)"""

    completed_by: str
    """Who completed this task"""


@dataclass(frozen=True)
class TaskArchivedEvent:
    """Event emitted when a task is archived.

    Archived tasks are moved out of active view but remain in history.
    """

    task_id: str
    """ID of the task being archived"""

    archived_at: datetime
    """When the task was archived"""

    archived_by: str
    """Who archived this task"""

    reason: str | None = None
    """Optional reason for archiving"""


@dataclass(frozen=True)
class TaskUpdatedEvent:
    """Event emitted when task metadata is updated.

    Used for updating assignee, priority, or other metadata.
    """

    task_id: str
    """ID of the task being updated"""

    updated_at: datetime
    """When the task was updated"""

    updated_by: str
    """Who updated this task"""

    changes: dict[str, Any]
    """Dictionary of field changes: {field_name: new_value}"""


# Event type constants for registration
TASK_CREATED = "task.created"
TASK_STARTED = "task.started"
TASK_COMPLETED = "task.completed"
TASK_ARCHIVED = "task.archived"
TASK_UPDATED = "task.updated"
