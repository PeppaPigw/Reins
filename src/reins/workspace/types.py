from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class JournalEntry:
    """A single developer session stored in markdown journals."""

    timestamp: datetime
    session_id: str
    title: str
    commits: list[str]
    summary: str
    tasks_completed: list[str]
    files_changed: list[str]
    details: str = ""


@dataclass(frozen=True)
class JournalFileStats:
    """Summary information for one journal file."""

    path: Path
    line_count: int
    session_start: int | None = None
    session_end: int | None = None


@dataclass(frozen=True)
class WorkspaceStats:
    """Developer workspace statistics persisted in `.stats.json`."""

    developer: str
    total_sessions: int = 0
    total_commits: int = 0
    last_active: datetime | None = None
    first_session: datetime | None = None
    journal_files: int = 0
    active_tasks: list[str] = field(default_factory=list)
    active_task_count: int = 0
    completed_tasks: int = 0
    total_lines: int = 0
    archived_journal_files: int = 0
    current_session_id: str | None = None
    files_changed: int = 0
    lines_added: int = 0
    lines_removed: int = 0


@dataclass(frozen=True)
class ActivityReport:
    """Developer activity summary for a time window."""

    developer: str
    period: str
    sessions_count: int
    commits_count: int
    tasks_completed: int
    files_changed: int
    lines_added: int
    lines_removed: int
