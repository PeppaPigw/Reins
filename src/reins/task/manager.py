"""Task manager — creates and manages task lifecycle.

The TaskManager is the command side of the task management system.
It emits events to the journal and queries the projection for reads.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.event.journal import EventJournal
from reins.kernel.event.task_events import (
    TASK_ARCHIVED,
    TASK_COMPLETED,
    TASK_CREATED,
    TASK_STARTED,
    TASK_UPDATED,
)
from reins.kernel.types import Actor
from reins.task.metadata import TaskMetadata, TaskStatus
from reins.task.projection import TaskContext, TaskContextProjection


class TaskManager:
    """Manages task lifecycle: create, start, complete, archive.

    This is the command side (write model) of the task management system.
    It emits events to the journal and queries the projection for reads.
    """

    def __init__(
        self,
        journal: EventJournal,
        projection: TaskContextProjection,
        run_id: str,
    ) -> None:
        self._journal = journal
        self._projection = projection
        self._run_id = run_id

    async def create_task(
        self,
        title: str,
        task_type: str,
        prd_content: str,
        acceptance_criteria: list[str],
        created_by: str,
        slug: str | None = None,
        priority: str = "P1",
        assignee: str = "unassigned",
        branch: str | None = None,
        base_branch: str = "main",
        parent_task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Create a new task.

        Args:
            title: Task title
            task_type: Type of task ('backend', 'frontend', etc.)
            prd_content: Product Requirements Document (markdown)
            acceptance_criteria: List of acceptance criteria
            created_by: Who is creating this task
            slug: URL-friendly slug (auto-generated if None)
            priority: Priority level ('P0', 'P1', 'P2', 'P3')
            assignee: Who is assigned (default: 'unassigned')
            branch: Git branch (auto-generated if None)
            base_branch: Base branch to merge into
            parent_task_id: Parent task ID if this is a subtask
            metadata: Additional metadata

        Returns:
            task_id of the created task
        """
        # Generate task_id from date and slug
        now = datetime.now(UTC)
        date_prefix = now.strftime("%m-%d")

        if slug is None:
            # Generate slug from title
            slug = self._generate_slug(title)

        task_id = f"{date_prefix}-{slug}"

        # Generate branch name if not provided
        if branch is None:
            branch = f"feat/{slug}"

        # Create event payload
        payload = {
            "task_id": task_id,
            "title": title,
            "slug": slug,
            "task_type": task_type,
            "prd_content": prd_content,
            "acceptance_criteria": acceptance_criteria,
            "priority": priority,
            "assignee": assignee,
            "branch": branch,
            "base_branch": base_branch,
            "created_by": created_by,
            "created_at": now.isoformat(),
            "parent_task_id": parent_task_id,
            "metadata": metadata or {},
        }

        # Emit event
        event = EventEnvelope(
            run_id=self._run_id,
            actor=Actor.SYSTEM,
            type=TASK_CREATED,
            payload=payload,
        )

        await self._journal.append(event)

        # Apply to projection
        self._projection.apply_event(event)

        return task_id

    async def start_task(self, task_id: str, assignee: str) -> None:
        """Start a task (transition from pending to in_progress).

        Args:
            task_id: ID of task to start
            assignee: Who is starting the task

        Raises:
            ValueError: If task doesn't exist or is not pending
        """
        task = self._projection.get_task(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        if task.status != TaskStatus.PENDING:
            raise ValueError(
                f"Task {task_id} is {task.status}, cannot start (must be pending)"
            )

        # Create event payload
        payload = {
            "task_id": task_id,
            "assignee": assignee,
            "started_at": datetime.now(UTC).isoformat(),
        }

        # Emit event
        event = EventEnvelope(
            run_id=self._run_id,
            actor=Actor.SYSTEM,
            type=TASK_STARTED,
            payload=payload,
        )

        await self._journal.append(event)

        # Apply to projection
        self._projection.apply_event(event)

    async def complete_task(
        self,
        task_id: str,
        outcome: dict[str, Any],
        completed_by: str = "system",
    ) -> None:
        """Complete a task (transition from in_progress to completed).

        Args:
            task_id: ID of task to complete
            outcome: Outcome data (files_modified, tests_added, etc.)
            completed_by: Who completed the task

        Raises:
            ValueError: If task doesn't exist or is not in_progress
        """
        task = self._projection.get_task(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        if task.status != TaskStatus.IN_PROGRESS:
            raise ValueError(
                f"Task {task_id} is {task.status}, cannot complete (must be in_progress)"
            )

        # Create event payload
        payload = {
            "task_id": task_id,
            "completed_at": datetime.now(UTC).isoformat(),
            "outcome": outcome,
            "completed_by": completed_by,
        }

        # Emit event
        event = EventEnvelope(
            run_id=self._run_id,
            actor=Actor.SYSTEM,
            type=TASK_COMPLETED,
            payload=payload,
        )

        await self._journal.append(event)

        # Apply to projection
        self._projection.apply_event(event)

    async def archive_task(
        self,
        task_id: str,
        archived_by: str = "system",
        reason: str | None = None,
    ) -> None:
        """Archive a task (remove from active view).

        Args:
            task_id: ID of task to archive
            archived_by: Who archived the task
            reason: Optional reason for archiving

        Raises:
            ValueError: If task doesn't exist
        """
        task = self._projection.get_task(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        # Create event payload
        payload = {
            "task_id": task_id,
            "archived_at": datetime.now(UTC).isoformat(),
            "archived_by": archived_by,
            "reason": reason,
        }

        # Emit event
        event = EventEnvelope(
            run_id=self._run_id,
            actor=Actor.SYSTEM,
            type=TASK_ARCHIVED,
            payload=payload,
        )

        await self._journal.append(event)

        # Apply to projection
        self._projection.apply_event(event)

    async def update_task(
        self,
        task_id: str,
        changes: dict[str, Any],
        updated_by: str = "system",
    ) -> None:
        """Update task metadata.

        Args:
            task_id: ID of task to update
            changes: Dictionary of field changes
            updated_by: Who is updating the task

        Raises:
            ValueError: If task doesn't exist
        """
        task = self._projection.get_task(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        # Create event payload
        payload = {
            "task_id": task_id,
            "updated_at": datetime.now(UTC).isoformat(),
            "updated_by": updated_by,
            "changes": changes,
        }

        # Emit event
        event = EventEnvelope(
            run_id=self._run_id,
            actor=Actor.SYSTEM,
            type=TASK_UPDATED,
            payload=payload,
        )

        await self._journal.append(event)

        # Apply to projection
        self._projection.apply_event(event)

    def get_task(self, task_id: str) -> TaskMetadata | None:
        """Get task metadata by ID (read from projection)."""
        return self._projection.get_task(task_id)

    def get_task_context(self, task_id: str) -> TaskContext | None:
        """Get complete task context by ID (read from projection)."""
        return self._projection.get_task_context(task_id)

    def list_tasks(
        self,
        status: TaskStatus | None = None,
        assignee: str | None = None,
        task_type: str | None = None,
        include_archived: bool = False,
    ) -> list[TaskMetadata]:
        """List tasks matching criteria (read from projection)."""
        return self._projection.list_tasks(
            status=status,
            assignee=assignee,
            task_type=task_type,
            include_archived=include_archived,
        )

    def _generate_slug(self, title: str) -> str:
        """Generate URL-friendly slug from title.

        Examples:
            "Implement JWT Authentication" -> "implement-jwt-authentication"
            "Fix Bug in Login Flow" -> "fix-bug-in-login-flow"
        """
        # Convert to lowercase
        slug = title.lower()

        # Replace spaces and special chars with hyphens
        import re

        slug = re.sub(r"[^\w\s-]", "", slug)
        slug = re.sub(r"[-\s]+", "-", slug)

        # Trim hyphens from ends
        slug = slug.strip("-")

        # Limit length
        if len(slug) > 50:
            slug = slug[:50].rstrip("-")

        return slug
