from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reins.workspace.journal import DeveloperJournal
from reins.workspace.manager import WorkspaceManager
from reins.workspace.types import JournalEntry


def make_entry(session_id: str, *, developer: str, timestamp: datetime) -> JournalEntry:
    return JournalEntry(
        timestamp=timestamp,
        session_id=session_id,
        title=f"{developer} session",
        commits=[f"{developer}-commit"],
        summary=f"Summary for {developer}",
        tasks_completed=[f"Task #{developer}: Work"],
        files_changed=[f"src/{developer}.py"],
        details="Workspace index integration test",
    )


def test_global_workspace_index_is_created_and_updated(tmp_path: Path) -> None:
    reins_root = tmp_path / ".reins"
    manager = WorkspaceManager(reins_root)

    manager.initialize_workspace("peppa")
    manager.initialize_workspace("george")

    workspace_index = reins_root / "workspace" / "index.md"
    initial = workspace_index.read_text(encoding="utf-8")
    assert "[GETTING_STARTED.md](GETTING_STARTED.md)" in initial
    assert "| peppa | - | 0 | 0 | journal-1.md |" in initial
    assert "| george | - | 0 | 0 | journal-1.md |" in initial

    DeveloperJournal(reins_root / "workspace", "peppa").add_session(
        make_entry(
            "peppa-session",
            developer="peppa",
            timestamp=datetime(2026, 4, 19, 9, 0, 0),
        )
    )

    updated = workspace_index.read_text(encoding="utf-8")
    assert "| peppa | 2026-04-19 | 1 | 1 | journal-1.md |" in updated
    assert "| george | - | 0 | 0 | journal-1.md |" in updated
