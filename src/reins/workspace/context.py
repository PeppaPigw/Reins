from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from reins.export.task_exporter import TaskExporter
from reins.kernel.event.builder import EventBuilder
from reins.kernel.event.envelope import event_from_dict
from reins.kernel.event.journal import EventJournal
from reins.kernel.event.workspace_events import WORKSPACE_TASK_ASSIGNED
from reins.task.manager import TaskManager
from reins.task.metadata import TaskMetadata
from reins.task.projection import TaskContextProjection


class DeveloperContext:
    """Manage developer identity, workspace session state, and task assignment."""

    def __init__(
        self,
        reins_root: Path,
        *,
        journal: EventJournal | None = None,
        run_id: str | None = None,
    ):
        self.reins_root = reins_root
        self._current_developer: str | None = None
        self._journal = journal or EventJournal(reins_root / "journal.jsonl")
        self._run_id = run_id or "developer-context"

    def get_current_developer(self) -> str | None:
        """Return the currently configured developer identity."""
        if self._current_developer:
            return self._current_developer

        developer_path = self.reins_root / ".developer"
        if not developer_path.exists():
            return None

        content = developer_path.read_text(encoding="utf-8").strip()
        if not content:
            return None

        for line in content.splitlines():
            if line.startswith("name="):
                self._current_developer = line.split("=", 1)[1].strip() or None
                return self._current_developer

        self._current_developer = content.splitlines()[0].strip() or None
        return self._current_developer

    def set_current_developer(self, developer: str) -> None:
        """Persist the current developer identity to `.reins/.developer`."""
        developer_path = self.reins_root / ".developer"
        developer_path.parent.mkdir(parents=True, exist_ok=True)
        developer_path.write_text(
            f"name={developer}\ninitialized_at={datetime.now(UTC).isoformat()}\n",
            encoding="utf-8",
        )
        self._current_developer = developer

    def detect_developer_from_git(self) -> str | None:
        """Detect the current developer from git config."""
        repo_root = self.reins_root.parent
        try:
            result = subprocess.run(
                ["git", "config", "user.name"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return None

        detected = result.stdout.strip() or None
        if detected:
            self._current_developer = detected
        return detected

    def get_current_session_id(self, developer: str | None = None) -> str | None:
        """Return the active session id for a developer workspace."""
        resolved = developer or self.get_current_developer()
        if resolved is None:
            return None

        session_path = self.reins_root / "workspace" / resolved / ".current-session"
        if not session_path.exists():
            return None
        return session_path.read_text(encoding="utf-8").strip() or None

    def get_developer_tasks(self, developer: str) -> list[TaskMetadata]:
        """Return active tasks assigned to a developer."""
        projection = self._load_projection()
        return projection.list_tasks(assignee=developer, include_archived=False)

    def assign_task(self, task_id: str, developer: str) -> None:
        """Assign a task to a developer and emit a tracking event."""
        projection = self._load_projection()
        manager = TaskManager(self._journal, projection, run_id=self._run_id)
        updated_by = self.get_current_developer() or developer
        asyncio.run(
            manager.update_task(
                task_id,
                {"assignee": developer, "metadata": {"assigned_to": developer}},
                updated_by=updated_by,
            )
        )
        TaskExporter(projection, self.reins_root / "tasks").export_task(task_id)

        builder = EventBuilder(self._journal)
        asyncio.run(
            builder.commit(
                run_id=self._run_id,
                event_type=WORKSPACE_TASK_ASSIGNED,
                payload={"task_id": task_id, "developer": developer, "assigned_by": updated_by},
            )
        )

    def update_event_payload(self, payload: dict[str, object]) -> dict[str, object]:
        """Add developer/session context into a payload when available."""
        updated = dict(payload)
        developer = self.get_current_developer()
        if developer and "developer" not in updated:
            updated["developer"] = developer
        session_id = self.get_current_session_id(developer)
        if session_id and "session_id" not in updated:
            updated["session_id"] = session_id
        return updated

    def _load_projection(self) -> TaskContextProjection:
        projection = TaskContextProjection()
        journal_path = self.reins_root / "journal.jsonl"
        if not journal_path.exists():
            return projection

        for line in journal_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            projection.apply_event(event_from_dict(json.loads(line)))
        return projection
