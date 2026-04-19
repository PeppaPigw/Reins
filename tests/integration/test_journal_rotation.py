from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reins.workspace.journal import DeveloperJournal
from reins.workspace.types import JournalEntry


def make_entry(index: int, summary: str) -> JournalEntry:
    return JournalEntry(
        timestamp=datetime(2026, 4, 19, 12, index, 0),
        session_id=f"rotation-{index}",
        title=f"Rotation {index}",
        commits=[f"deadbeef{index}"],
        summary=summary,
        tasks_completed=[f"Task #{index}: Rotate"],
        files_changed=[f"src/rotation_{index}.py"],
        details=summary,
    )


def test_journal_rotates_and_preserves_history(tmp_path: Path) -> None:
    journal = DeveloperJournal(tmp_path / "workspace", "peppa")
    journal.max_lines_per_file = 20

    journal.add_session(make_entry(1, "A" * 200))
    journal.add_session(make_entry(2, "B" * 200))

    developer_dir = tmp_path / "workspace" / "peppa"
    journal_one = developer_dir / "journal-1.md"
    journal_two = developer_dir / "journal-2.md"

    assert journal_one.exists()
    assert journal_two.exists()

    first_content = journal_one.read_text(encoding="utf-8")
    second_content = journal_two.read_text(encoding="utf-8")
    assert "## Session 1: Rotation 1" in first_content
    assert "## Session 2: Rotation 2" in second_content

    entries = journal.get_all_entries()
    assert [entry.session_id for entry in entries] == ["rotation-1", "rotation-2"]

    index_content = (developer_dir / "index.md").read_text(encoding="utf-8")
    assert "[journal-1.md](journal-1.md)" in index_content
    assert "[journal-2.md](journal-2.md)" in index_content
    assert "Sessions 1-1" in index_content
    assert "Sessions 2-2" in index_content
