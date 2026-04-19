from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from reins.workspace.journal import DeveloperJournal
from reins.workspace.types import JournalEntry


def make_entry(index: int, *, title: str | None = None) -> JournalEntry:
    return JournalEntry(
        timestamp=datetime(2026, 4, 19, 10, index, 0),
        session_id=f"session-{index}",
        title=title or f"Session {index}",
        commits=[f"abc{index:03d}", f"def{index:03d}"],
        summary=f"Completed step {index}",
        tasks_completed=[f"Task #{index}: Demo task"],
        files_changed=[f"src/demo_{index}.py", f"tests/test_demo_{index}.py"],
        details=f"Detailed change log for session {index}.",
    )


def test_add_session_writes_markdown_and_updates_index(tmp_path: Path) -> None:
    journal = DeveloperJournal(tmp_path / "workspace", "peppa")
    journal.add_session(make_entry(1, title="Implement journal"))

    journal_file = tmp_path / "workspace" / "peppa" / "journal-1.md"
    assert journal_file.exists()
    content = journal_file.read_text(encoding="utf-8")
    assert "## Session 1: Implement journal" in content
    assert "**Session ID:** session-1" in content
    assert "### Tasks Completed" in content
    assert "src/demo_1.py" in content

    index_file = tmp_path / "workspace" / "peppa" / "index.md"
    assert index_file.exists()
    index_content = index_file.read_text(encoding="utf-8")
    assert "# Developer Workspace: peppa" in index_content
    assert "- **Total Sessions:** 1" in index_content
    assert "[Implement journal](journal-1.md#session-1)" in index_content

    current_session = (tmp_path / "workspace" / "peppa" / ".current-session").read_text(
        encoding="utf-8"
    )
    assert current_session.strip() == "session-1"


def test_get_all_entries_parses_multiple_sessions(tmp_path: Path) -> None:
    journal = DeveloperJournal(tmp_path / "workspace", "peppa")
    journal.add_session(make_entry(1))
    journal.add_session(make_entry(2))

    entries = journal.get_all_entries()
    assert [entry.session_id for entry in entries] == ["session-1", "session-2"]
    assert entries[1].title == "Session 2"
    assert entries[1].files_changed == ["src/demo_2.py", "tests/test_demo_2.py"]


def test_update_index_uses_active_tasks_from_stats_file(tmp_path: Path) -> None:
    journal = DeveloperJournal(tmp_path / "workspace", "peppa")
    journal.add_session(make_entry(1))

    stats_path = tmp_path / "workspace" / "peppa" / ".stats.json"
    stats_path.write_text(
        json.dumps({"active_tasks": ["Task #10: Workspace cleanup", "Task #11: Review"]}),
        encoding="utf-8",
    )

    journal.update_index()
    index_content = (tmp_path / "workspace" / "peppa" / "index.md").read_text(encoding="utf-8")
    assert "- Task #10: Workspace cleanup" in index_content
    assert "- Task #11: Review" in index_content
