from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from reins.kernel.event.envelope import event_from_dict
from reins.task.metadata import TaskMetadata, TaskStatus
from reins.task.projection import TaskContextProjection
from reins.workspace.journal import DeveloperJournal
from reins.workspace.types import WorkspaceStats


class StatisticsCalculator:
    """Calculate persisted workspace statistics for a developer."""

    def calculate_stats(self, workspace_dir: Path) -> WorkspaceStats:
        """Calculate all workspace statistics for one developer directory."""
        developer = workspace_dir.name
        reins_root = workspace_dir.parent.parent
        journal = DeveloperJournal(reins_root / "workspace", developer)
        entries = journal.get_all_entries()
        timestamps = [entry.timestamp for entry in entries]
        journal_files = sorted(workspace_dir.glob("journal-*.md"))
        archived_dir = workspace_dir / "archive"
        archived_journal_files = (
            len(list(archived_dir.glob("journal-*.md"))) if archived_dir.exists() else 0
        )
        tasks = self._load_developer_tasks(reins_root, developer)
        active_tasks = [task for task in tasks if task.status in {TaskStatus.PENDING, TaskStatus.IN_PROGRESS}]
        unique_commits = sorted({commit for entry in entries for commit in entry.commits})
        lines_added, lines_removed = self._calculate_code_changes(reins_root.parent, unique_commits)
        current_session_path = workspace_dir / ".current-session"
        current_session_id = None
        if current_session_path.exists():
            current_session_id = current_session_path.read_text(encoding="utf-8").strip() or None

        return WorkspaceStats(
            developer=developer,
            total_sessions=len(entries),
            total_commits=sum(len(entry.commits) for entry in entries),
            last_active=max(timestamps) if timestamps else None,
            first_session=min(timestamps) if timestamps else None,
            journal_files=len(journal_files),
            active_tasks=[f"{task.task_id}: {task.title}" for task in active_tasks],
            active_task_count=len(active_tasks),
            completed_tasks=sum(1 for task in tasks if task.completed_at is not None),
            total_lines=sum(_count_lines(path) for path in journal_files),
            archived_journal_files=archived_journal_files,
            current_session_id=current_session_id,
            files_changed=len({path for entry in entries for path in entry.files_changed}),
            lines_added=lines_added,
            lines_removed=lines_removed,
        )

    def _load_developer_tasks(self, reins_root: Path, developer: str) -> list[TaskMetadata]:
        projection = TaskContextProjection()
        journal_path = reins_root / "journal.jsonl"
        if not journal_path.exists():
            return []

        for line in journal_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            projection.apply_event(event_from_dict(json.loads(line)))

        return projection.list_tasks(assignee=developer, include_archived=True)

    def _calculate_code_changes(self, repo_root: Path, commits: list[str]) -> tuple[int, int]:
        return sum_git_numstat(repo_root, commits)


def build_workspace_stats(
    developer: str,
    journal: DeveloperJournal,
    *,
    active_tasks: list[str] | None = None,
    archived_journal_files: int = 0,
    current_session_id: str | None = None,
) -> WorkspaceStats:
    """Compute persisted workspace stats from the journal state."""
    del developer, active_tasks, archived_journal_files, current_session_id
    return StatisticsCalculator().calculate_stats(journal.journal_dir)


def load_workspace_stats(workspace_dir: Path, developer: str) -> WorkspaceStats:
    """Load workspace stats from disk, falling back to defaults."""
    stats_path = workspace_dir / ".stats.json"
    if not stats_path.exists():
        return WorkspaceStats(developer=developer)

    payload = json.loads(stats_path.read_text(encoding="utf-8"))
    last_active_raw = payload.get("last_active")
    first_session_raw = payload.get("first_session")
    return WorkspaceStats(
        developer=str(payload.get("developer", developer)),
        total_sessions=int(payload.get("total_sessions", 0)),
        total_commits=int(payload.get("total_commits", 0)),
        last_active=datetime.fromisoformat(last_active_raw) if last_active_raw else None,
        first_session=datetime.fromisoformat(first_session_raw) if first_session_raw else None,
        journal_files=int(payload.get("journal_files", 0)),
        active_tasks=[str(item) for item in payload.get("active_tasks", [])],
        active_task_count=int(payload.get("active_task_count", 0)),
        completed_tasks=int(payload.get("completed_tasks", 0)),
        total_lines=int(payload.get("total_lines", 0)),
        archived_journal_files=int(payload.get("archived_journal_files", 0)),
        current_session_id=payload.get("current_session_id"),
        files_changed=int(payload.get("files_changed", 0)),
        lines_added=int(payload.get("lines_added", 0)),
        lines_removed=int(payload.get("lines_removed", 0)),
    )


def write_workspace_stats(workspace_dir: Path, stats: WorkspaceStats) -> Path:
    """Persist workspace stats to `.stats.json`."""
    path = workspace_dir / ".stats.json"
    payload = asdict(stats)
    payload["last_active"] = stats.last_active.isoformat() if stats.last_active else None
    payload["first_session"] = stats.first_session.isoformat() if stats.first_session else None
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def sum_git_numstat(repo_root: Path, commits: list[str]) -> tuple[int, int]:
    """Sum line additions and removals across git commits."""
    if not commits:
        return 0, 0

    added = 0
    removed = 0
    for commit in commits:
        try:
            result = subprocess.run(
                ["git", "show", "--numstat", "--format=", commit],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError):
            continue

        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            if parts[0].isdigit():
                added += int(parts[0])
            if parts[1].isdigit():
                removed += int(parts[1])
    return added, removed


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())
