"""Task exporter - exports tasks to filesystem for platform interop.

Exports TaskMetadata and context to `.reins/tasks/` directory structure.
These are derived artifacts for platform interop and human review.
"""

from __future__ import annotations

import json
from pathlib import Path

from reins.task.context_jsonl import ContextMessage, ContextJSONL
from reins.task.metadata import TaskMetadata, TaskStatus
from reins.task.projection import TaskContextProjection


class TaskExporter:
    """Exports tasks to filesystem.

    Reads from TaskContextProjection and writes to `.reins/tasks/` directory.
    """

    def __init__(
        self,
        projection: TaskContextProjection,
        export_dir: Path,
    ) -> None:
        """Initialize task exporter.

        Args:
            projection: Task projection to export from
            export_dir: Base directory for exports (e.g., `.reins/tasks/`)
        """
        self._projection = projection
        self._export_dir = export_dir

    def export_all(self, include_archived: bool = False) -> list[Path]:
        """Export all tasks to filesystem.

        Args:
            include_archived: Whether to include archived tasks

        Returns:
            List of paths to exported task directories
        """
        exported_dirs: list[Path] = []

        # Get all tasks
        tasks = self._projection.list_tasks(include_archived=include_archived)

        for task in tasks:
            task_dir = self._export_task(task)
            exported_dirs.append(task_dir)

        return exported_dirs

    def export_task(self, task_id: str) -> Path | None:
        """Export a single task to filesystem.

        Args:
            task_id: ID of task to export

        Returns:
            Path to exported task directory, or None if task not found
        """
        task = self._projection.get_task(task_id)
        if not task:
            return None

        return self._export_task(task)

    def _export_task(self, task: TaskMetadata) -> Path:
        """Export task to filesystem.

        Args:
            task: Task metadata to export

        Returns:
            Path to exported task directory
        """
        # Create task directory
        task_dir = self._export_dir / task.task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        # Export task.json
        self._export_task_json(task_dir, task)

        # Export prd.md
        self._export_prd(task_dir, task)

        return task_dir

    def _export_task_json(self, task_dir: Path, task: TaskMetadata) -> None:
        """Export task metadata to task.json.

        Args:
            task_dir: Task directory
            task: Task metadata
        """
        task_json = {
            "task_id": task.task_id,
            "title": task.title,
            "slug": task.slug,
            "task_type": task.task_type,
            "priority": task.priority,
            "assignee": task.assignee,
            "status": task.status.value,
            "branch": task.branch,
            "base_branch": task.base_branch,
            "created_by": task.created_by,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "parent_task_id": task.parent_task_id,
            "metadata": task.metadata,
        }
        if "assigned_to" in task.metadata:
            task_json["assigned_to"] = task.metadata["assigned_to"]

        task_json_path = task_dir / "task.json"
        with open(task_json_path, "w", encoding="utf-8") as f:
            json.dump(task_json, f, indent=2, ensure_ascii=False)

    def _export_prd(self, task_dir: Path, task: TaskMetadata) -> None:
        """Export PRD to prd.md.

        Args:
            task_dir: Task directory
            task: Task metadata
        """
        prd_path = task_dir / "prd.md"

        # Create PRD content
        lines = [
            f"# {task.title}\n",
            "\n",
            "## Goal\n",
            "\n",
            f"{task.prd_content}\n",
            "\n",
            "## Acceptance Criteria\n",
            "\n",
        ]

        for criterion in task.acceptance_criteria:
            lines.append(f"- [ ] {criterion}\n")

        lines.append("\n")
        lines.append("## Metadata\n")
        lines.append("\n")
        lines.append(f"- **Task ID**: {task.task_id}\n")
        lines.append(f"- **Type**: {task.task_type}\n")
        lines.append(f"- **Priority**: {task.priority}\n")
        lines.append(f"- **Assignee**: {task.assignee}\n")
        lines.append(f"- **Status**: {task.status.value}\n")
        lines.append(f"- **Branch**: {task.branch}\n")
        lines.append(f"- **Base Branch**: {task.base_branch}\n")

        if task.parent_task_id:
            lines.append(f"- **Parent Task**: {task.parent_task_id}\n")

        with open(prd_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

    def export_context(
        self, task_id: str, agent: str, messages: list[ContextMessage]
    ) -> Path | None:
        """Export agent context to JSONL file.

        Args:
            task_id: Task ID
            agent: Agent name (e.g., 'implement', 'check', 'debug')
            messages: List of context messages

        Returns:
            Path to exported JSONL file, or None if task not found
        """
        task = self._projection.get_task(task_id)
        if not task:
            return None

        task_dir = self._export_dir / task.task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        jsonl_path = task_dir / f"{agent}.jsonl"

        # Clear existing file
        if jsonl_path.exists():
            jsonl_path.unlink()

        # Write messages
        for message in messages:
            ContextJSONL.write_message(jsonl_path, message)

        return jsonl_path

    def set_current_task(self, task_id: str | None) -> None:
        """Set the current task pointer.

        Args:
            task_id: Task ID to set as current, or None to clear
        """
        current_task_file = self._export_dir.parent / ".current-task"

        if task_id is None:
            # Clear current task
            if current_task_file.exists():
                current_task_file.unlink()
        else:
            # Set current task
            task = self._projection.get_task(task_id)
            if task:
                # Write relative path to task directory
                task_dir_rel = f"tasks/{task.task_id}"
                with open(current_task_file, "w", encoding="utf-8") as f:
                    f.write(task_dir_rel)

    def get_current_task(self) -> str | None:
        """Get the current task ID.

        Returns:
            Current task ID, or None if no current task
        """
        current_task_file = self._export_dir.parent / ".current-task"

        if not current_task_file.exists():
            return None

        with open(current_task_file, "r", encoding="utf-8") as f:
            task_dir_rel = f.read().strip()

        # Extract task ID from relative path
        # Format: "tasks/{task_id}"
        parts = task_dir_rel.split("/")
        if len(parts) >= 2:
            return parts[-1]

        return None

    def cleanup_orphans(self) -> list[Path]:
        """Remove task directories for tasks that no longer exist.

        Returns:
            List of paths that were removed
        """
        removed: list[Path] = []

        if not self._export_dir.exists():
            return removed

        # Get all active task IDs
        active_ids = {t.task_id for t in self._projection.list_tasks(include_archived=True)}

        # Find all task directories
        for task_dir in self._export_dir.iterdir():
            if not task_dir.is_dir():
                continue

            task_id = task_dir.name

            if task_id not in active_ids:
                # Remove directory and all contents
                import shutil
                shutil.rmtree(task_dir)
                removed.append(task_dir)

        return removed

    def create_index(self) -> Path:
        """Create index.md file listing all tasks.

        Returns:
            Path to index file
        """
        # Ensure export directory exists
        self._export_dir.mkdir(parents=True, exist_ok=True)

        index_path = self._export_dir / "index.md"

        lines = [
            "# Tasks\n",
            "\n",
            "## Active Tasks\n",
            "\n",
        ]

        # Group by status
        pending = self._projection.get_tasks_by_status(TaskStatus.PENDING)
        in_progress = self._projection.get_tasks_by_status(TaskStatus.IN_PROGRESS)
        completed = self._projection.get_tasks_by_status(TaskStatus.COMPLETED)

        if pending:
            lines.append("### Pending\n\n")
            for task in sorted(pending, key=lambda t: t.created_at or ""):
                lines.append(f"- [{task.task_id}]({task.task_id}/prd.md) - {task.title}\n")
            lines.append("\n")

        if in_progress:
            lines.append("### In Progress\n\n")
            for task in sorted(in_progress, key=lambda t: t.started_at or ""):
                lines.append(f"- [{task.task_id}]({task.task_id}/prd.md) - {task.title}\n")
            lines.append("\n")

        if completed:
            lines.append("### Completed\n\n")
            for task in sorted(completed, key=lambda t: t.completed_at or "", reverse=True):
                lines.append(f"- [{task.task_id}]({task.task_id}/prd.md) - {task.title}\n")
            lines.append("\n")

        with open(index_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        return index_path
