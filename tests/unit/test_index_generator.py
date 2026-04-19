from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reins.workspace.index_generator import WorkspaceIndexGenerator
from reins.workspace.journal import DeveloperJournal
from reins.workspace.types import JournalEntry


def make_entry(
    session_id: str,
    *,
    title: str,
    timestamp: datetime,
    commits: list[str] | None = None,
) -> JournalEntry:
    return JournalEntry(
        timestamp=timestamp,
        session_id=session_id,
        title=title,
        commits=commits or [f"{session_id}-commit"],
        summary=f"Summary for {title}",
        tasks_completed=[f"Task #{session_id}: Demo task"],
        files_changed=[f"src/{session_id}.py"],
        details=f"Detailed notes for {title}",
    )


def test_generate_index_lists_all_developers_sorted_by_recent_activity(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    peppa = DeveloperJournal(workspace_root, "peppa")
    george = DeveloperJournal(workspace_root, "george")

    peppa.add_session(
        make_entry(
            "peppa-1",
            title="Peppa Session",
            timestamp=datetime(2026, 4, 18, 9, 0, 0),
        )
    )
    george.add_session(
        make_entry(
            "george-1",
            title="George Session",
            timestamp=datetime(2026, 4, 19, 10, 30, 0),
            commits=["abc123", "def456"],
        )
    )

    content = WorkspaceIndexGenerator(workspace_root).generate_index()

    assert "# Workspace Index" in content
    assert "[GETTING_STARTED.md](GETTING_STARTED.md)" in content
    assert "| george | 2026-04-19 | 1 | 2 | journal-1.md |" in content
    assert "| peppa | 2026-04-18 | 1 | 1 | journal-1.md |" in content
    assert content.index("| george |") < content.index("| peppa |")


def test_generate_index_handles_empty_workspace(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True)

    content = WorkspaceIndexGenerator(workspace_root).generate_index()

    assert "| _None yet_ | - | 0 | 0 | - |" in content
