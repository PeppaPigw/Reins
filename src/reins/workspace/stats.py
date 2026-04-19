from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from reins.workspace.journal import DeveloperJournal
from reins.workspace.types import WorkspaceStats


def build_workspace_stats(
    developer: str,
    journal: DeveloperJournal,
    *,
    active_tasks: list[str] | None = None,
    archived_journal_files: int = 0,
    current_session_id: str | None = None,
) -> WorkspaceStats:
    """Compute persisted workspace stats from the journal state."""
    entries = journal.get_all_entries()
    journal_files = sorted(journal.journal_dir.glob("journal-*.md"))
    total_lines = sum(_count_lines(path) for path in journal_files)

    return WorkspaceStats(
        developer=developer,
        total_sessions=len(entries),
        total_commits=sum(len(entry.commits) for entry in entries),
        last_active=entries[-1].timestamp if entries else None,
        journal_files=len(journal_files),
        active_tasks=active_tasks or [],
        total_lines=total_lines,
        archived_journal_files=archived_journal_files,
        current_session_id=current_session_id,
    )


def load_workspace_stats(workspace_dir: Path, developer: str) -> WorkspaceStats:
    """Load workspace stats from disk, falling back to defaults."""
    stats_path = workspace_dir / ".stats.json"
    if not stats_path.exists():
        return WorkspaceStats(developer=developer)

    payload = json.loads(stats_path.read_text(encoding="utf-8"))
    last_active_raw = payload.get("last_active")
    return WorkspaceStats(
        developer=str(payload.get("developer", developer)),
        total_sessions=int(payload.get("total_sessions", 0)),
        total_commits=int(payload.get("total_commits", 0)),
        last_active=datetime.fromisoformat(last_active_raw) if last_active_raw else None,
        journal_files=int(payload.get("journal_files", 0)),
        active_tasks=[str(item) for item in payload.get("active_tasks", [])],
        total_lines=int(payload.get("total_lines", 0)),
        archived_journal_files=int(payload.get("archived_journal_files", 0)),
        current_session_id=payload.get("current_session_id"),
    )


def write_workspace_stats(workspace_dir: Path, stats: WorkspaceStats) -> Path:
    """Persist workspace stats to `.stats.json`."""
    path = workspace_dir / ".stats.json"
    payload = asdict(stats)
    payload["last_active"] = stats.last_active.isoformat() if stats.last_active else None
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())
