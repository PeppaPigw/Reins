"""Task context projection — builds queryable index from task events.

The projection consumes task events from the journal and maintains
an in-memory index for fast queries. This is the read model for tasks.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.event.task_events import (
    TASK_ARCHIVED,
    TASK_COMPLETED,
    TASK_CREATED,
    TASK_STARTED,
    TASK_UPDATED,
)
from reins.task.metadata import TaskMetadata, TaskStatus


@dataclass(frozen=True)
class TaskContext:
    """Complete context for a task.

    Includes metadata, PRD, and any additional context accumulated
    during the task lifecycle.
    """

    metadata: TaskMetadata
    """Core task metadata"""

    events: list[dict[str, Any]]
    """All events for this task (for audit trail)"""

    decisions: list[dict[str, Any]]
    """Decisions made during task execution"""

    def get_prd(self) -> str:
        """Get the PRD content."""
        return self.metadata.prd_content

    def is_active(self) -> bool:
        """Check if task is active (not archived)."""
        return self.metadata.status != TaskStatus.ARCHIVED


class TaskContextProjection:
    """Projection that builds a queryable index of tasks from events.

    This is the read model for the task management system.
    It maintains:
    - Primary index: tasks by task_id
    - Secondary indexes: by status, by assignee
    - Event history per task
    """

    def __init__(self) -> None:
        # Primary index: task_id -> TaskMetadata
        self._tasks: dict[str, TaskMetadata] = {}

        # Event history: task_id -> list of event payloads
        self._event_history: dict[str, list[dict[str, Any]]] = {}

        # Decisions: task_id -> list of decisions
        self._decisions: dict[str, list[dict[str, Any]]] = {}

    def apply_event(self, event: EventEnvelope) -> None:
        """Apply an event to update the projection state."""
        if event.type == TASK_CREATED:
            self._apply_task_created(event)
        elif event.type == TASK_STARTED:
            self._apply_task_started(event)
        elif event.type == TASK_COMPLETED:
            self._apply_task_completed(event)
        elif event.type == TASK_ARCHIVED:
            self._apply_task_archived(event)
        elif event.type == TASK_UPDATED:
            self._apply_task_updated(event)

    def _apply_task_created(self, event: EventEnvelope) -> None:
        """Handle TaskCreatedEvent."""
        payload = event.payload

        metadata = TaskMetadata(
            task_id=payload["task_id"],
            title=payload["title"],
            slug=payload["slug"],
            task_type=payload["task_type"],
            prd_content=payload["prd_content"],
            acceptance_criteria=payload["acceptance_criteria"],
            priority=payload["priority"],
            assignee=payload["assignee"],
            status=TaskStatus.PENDING,
            branch=payload["branch"],
            base_branch=payload["base_branch"],
            created_by=payload["created_by"],
            created_at=event.ts,
            parent_task_id=payload.get("parent_task_id"),
            metadata=payload.get("metadata", {}),
        )

        self._tasks[metadata.task_id] = metadata
        self._event_history[metadata.task_id] = [payload]
        self._decisions[metadata.task_id] = []

    def _apply_task_started(self, event: EventEnvelope) -> None:
        """Handle TaskStartedEvent."""
        payload = event.payload
        task_id = payload["task_id"]

        if task_id in self._tasks:
            old_metadata = self._tasks[task_id]
            self._tasks[task_id] = replace(
                old_metadata,
                status=TaskStatus.IN_PROGRESS,
                assignee=payload["assignee"],
                started_at=event.ts,
            )
            self._event_history[task_id].append(payload)

    def _apply_task_completed(self, event: EventEnvelope) -> None:
        """Handle TaskCompletedEvent."""
        payload = event.payload
        task_id = payload["task_id"]

        if task_id in self._tasks:
            old_metadata = self._tasks[task_id]
            self._tasks[task_id] = replace(
                old_metadata,
                status=TaskStatus.COMPLETED,
                completed_at=event.ts,
            )
            self._event_history[task_id].append(payload)

    def _apply_task_archived(self, event: EventEnvelope) -> None:
        """Handle TaskArchivedEvent."""
        payload = event.payload
        task_id = payload["task_id"]

        if task_id in self._tasks:
            old_metadata = self._tasks[task_id]
            self._tasks[task_id] = replace(
                old_metadata,
                status=TaskStatus.ARCHIVED,
            )
            self._event_history[task_id].append(payload)

    def _apply_task_updated(self, event: EventEnvelope) -> None:
        """Handle TaskUpdatedEvent."""
        payload = event.payload
        task_id = payload["task_id"]
        changes = payload["changes"]

        if task_id in self._tasks:
            old_metadata = self._tasks[task_id]

            # Apply changes
            updates = {}
            if "assignee" in changes:
                updates["assignee"] = changes["assignee"]
            if "priority" in changes:
                updates["priority"] = changes["priority"]
            if "metadata" in changes:
                # Merge metadata
                new_metadata = {**old_metadata.metadata, **changes["metadata"]}
                updates["metadata"] = new_metadata

            self._tasks[task_id] = replace(old_metadata, **updates)
            self._event_history[task_id].append(payload)

    def get_task(self, task_id: str) -> TaskMetadata | None:
        """Get task metadata by ID."""
        return self._tasks.get(task_id)

    def get_task_context(self, task_id: str) -> TaskContext | None:
        """Get complete task context by ID."""
        metadata = self._tasks.get(task_id)
        if not metadata:
            return None

        events = self._event_history.get(task_id, [])
        decisions = self._decisions.get(task_id, [])

        return TaskContext(
            metadata=metadata,
            events=events,
            decisions=decisions,
        )

    def list_tasks(
        self,
        status: TaskStatus | None = None,
        assignee: str | None = None,
        task_type: str | None = None,
        include_archived: bool = False,
    ) -> list[TaskMetadata]:
        """List tasks matching criteria.

        Args:
            status: Filter by status
            assignee: Filter by assignee
            task_type: Filter by task type
            include_archived: Include archived tasks

        Returns:
            List of TaskMetadata matching criteria
        """
        tasks = list(self._tasks.values())

        # Filter by status
        if status is not None:
            tasks = [t for t in tasks if t.status == status]

        # Filter archived
        if not include_archived:
            tasks = [t for t in tasks if t.status != TaskStatus.ARCHIVED]

        # Filter by assignee
        if assignee is not None:
            tasks = [t for t in tasks if t.assignee == assignee]

        # Filter by task_type
        if task_type is not None:
            tasks = [t for t in tasks if t.task_type == task_type]

        return tasks

    def count_tasks(self) -> int:
        """Count total tasks (including archived)."""
        return len(self._tasks)

    def count_active_tasks(self) -> int:
        """Count active tasks (excluding archived)."""
        return len([t for t in self._tasks.values() if t.status != TaskStatus.ARCHIVED])

    def count_by_status(self) -> dict[TaskStatus, int]:
        """Count tasks by status."""
        counts: dict[TaskStatus, int] = {
            TaskStatus.PENDING: 0,
            TaskStatus.IN_PROGRESS: 0,
            TaskStatus.COMPLETED: 0,
            TaskStatus.ARCHIVED: 0,
        }

        for task in self._tasks.values():
            counts[task.status] += 1

        return counts

    def get_subtasks(self, parent_task_id: str) -> list[TaskMetadata]:
        """Get all subtasks of a parent task."""
        return [
            t
            for t in self._tasks.values()
            if t.parent_task_id == parent_task_id
        ]

    def clear(self) -> None:
        """Clear all projection state. Used for testing."""
        self._tasks.clear()
        self._event_history.clear()
        self._decisions.clear()
