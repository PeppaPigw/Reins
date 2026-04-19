from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reins.kernel.event.journal import EventJournal
from reins.workspace.journal import DeveloperJournal
from reins.workspace.manager import WorkspaceManager
from reins.workspace.types import JournalEntry


def make_entry(session_id: str, *, developer: str) -> JournalEntry:
    return JournalEntry(
        timestamp=datetime(2026, 4, 19, 9, 0, 0),
        session_id=session_id,
        title=f"{developer} session",
        commits=[f"{developer}-commit"],
        summary=f"Summary for {developer}",
        tasks_completed=[f"Task #{developer}: Work"],
        files_changed=[f"src/{developer}.py"],
        details="Workspace isolation test",
    )


def test_multiple_developer_workspaces_are_isolated(tmp_path: Path) -> None:
    reins_root = tmp_path / ".reins"
    manager = WorkspaceManager(
        reins_root,
        journal=EventJournal(reins_root / "journal.jsonl"),
        run_id="workspace-integration",
    )

    peppa_dir = manager.initialize_workspace("peppa")
    george_dir = manager.initialize_workspace("george")

    DeveloperJournal(reins_root / "workspace", "peppa").add_session(
        make_entry("peppa-session", developer="peppa")
    )
    DeveloperJournal(reins_root / "workspace", "george").add_session(
        make_entry("george-session", developer="george")
    )

    assert peppa_dir != george_dir
    assert "peppa-session" in (peppa_dir / ".current-session").read_text(encoding="utf-8")
    assert "george-session" in (george_dir / ".current-session").read_text(encoding="utf-8")
    assert "peppa session" in (peppa_dir / "journal-1.md").read_text(encoding="utf-8")
    assert "george session" not in (peppa_dir / "journal-1.md").read_text(encoding="utf-8")

    stats = manager.get_workspace_stats("peppa")
    assert stats.total_sessions == 1
    assert stats.total_commits == 1
