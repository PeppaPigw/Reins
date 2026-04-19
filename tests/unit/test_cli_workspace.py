from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reins.workspace.journal import DeveloperJournal
from reins.workspace.manager import WorkspaceManager
from reins.workspace.types import JournalEntry
from tests.unit.cli_helpers import create_repo, invoke


def make_entry() -> JournalEntry:
    return JournalEntry(
        timestamp=datetime(2026, 4, 19, 12, 0, 0),
        session_id="session-1",
        title="Workspace CLI Session",
        commits=["abc123"],
        summary="CLI statistics output",
        tasks_completed=["Task #1: Check CLI"],
        files_changed=["src/workspace_cli.py"],
        details="CLI detailed statistics test entry",
    )


def test_workspace_stats_detailed_option(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path)
    manager = WorkspaceManager(repo / ".reins")
    manager.initialize_workspace("peppa")
    DeveloperJournal(repo / ".reins" / "workspace", "peppa").add_session(make_entry())

    result = invoke(repo, monkeypatch, ["workspace", "stats", "peppa", "--detailed"])

    assert result.exit_code == 0
    assert "first_session" in result.output
    assert "active_task_count" in result.output
    assert "completed_tasks" in result.output
    assert "files_changed" in result.output
    assert "lines_added" in result.output
    assert "lines_removed" in result.output
