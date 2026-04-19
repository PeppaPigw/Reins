from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reins.kernel.event.journal import EventJournal
from reins.workspace.journal import DeveloperJournal
from reins.workspace.manager import WorkspaceManager
from reins.workspace.types import JournalEntry


def make_entry(session_id: str, timestamp: datetime) -> JournalEntry:
    return JournalEntry(
        timestamp=timestamp,
        session_id=session_id,
        title=f"Title for {session_id}",
        commits=[f"{session_id}-commit"],
        summary=f"Summary for {session_id}",
        tasks_completed=[f"Task #{session_id}: Task"],
        files_changed=[f"src/{session_id}.py"],
        details="Detailed notes",
    )


def test_initialize_workspace_creates_layout_and_stats(tmp_path: Path) -> None:
    reins_root = tmp_path / ".reins"
    journal = EventJournal(reins_root / "journal.jsonl")
    manager = WorkspaceManager(reins_root, journal=journal, run_id="workspace-test")

    workspace_dir = manager.initialize_workspace("peppa")

    assert workspace_dir == reins_root / "workspace" / "peppa"
    assert (workspace_dir / "journal-1.md").exists()
    assert (workspace_dir / "index.md").exists()
    assert (workspace_dir / ".current-session").exists()
    assert (workspace_dir / ".stats.json").exists()

    stats = manager.get_workspace_stats("peppa")
    assert stats.developer == "peppa"
    assert stats.journal_files == 1
    assert stats.active_task_count == 0
    assert stats.completed_tasks == 0
    assert "peppa" in manager.list_workspaces()


def test_cleanup_workspace_archives_old_rotated_files(tmp_path: Path) -> None:
    reins_root = tmp_path / ".reins"
    manager = WorkspaceManager(reins_root)
    workspace_dir = manager.initialize_workspace("peppa")

    journal = DeveloperJournal(reins_root / "workspace", "peppa")
    journal.max_lines_per_file = 20
    journal.add_session(make_entry("old-session", datetime(2025, 1, 1, 10, 0, 0)))
    journal.add_session(make_entry("new-session", datetime.now()))

    manager.cleanup_workspace("peppa", keep_recent_days=30)

    assert not (workspace_dir / "journal-1.md").exists()
    assert (workspace_dir / "journal-2.md").exists()
    assert (workspace_dir / "archive" / "journal-1.md").exists()

    stats = manager.get_workspace_stats("peppa")
    assert stats.archived_journal_files == 1
