from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reins.config.loader import ConfigLoader
from reins.config.validator import validate_config
from reins.workspace.journal import DeveloperJournal
from reins.workspace.types import JournalEntry


def _make_entry(index: int, summary: str) -> JournalEntry:
    return JournalEntry(
        timestamp=datetime(2026, 4, 19, 9, index, 0),
        session_id=f"cfg-{index}",
        title=f"Config Session {index}",
        commits=[f"abc{index:03d}"],
        summary=summary,
        tasks_completed=[f"Task {index}"],
        files_changed=[f"src/config_{index}.py"],
        details=summary,
    )


def test_validate_config_reports_semantic_errors(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    reins_root = repo_root / ".reins"
    reins_root.mkdir()
    (reins_root / "config.yaml").write_text(
        """
max_journal_lines: 20
packages:
  cli:
    path: packages/cli
    type: plugin
default_package: docs
""".strip(),
        encoding="utf-8",
    )

    config = ConfigLoader(reins_root).load()
    errors = validate_config(config, repo_root=repo_root)

    assert "max_journal_lines must be >= 100" in errors
    assert "Package 'cli' has invalid type 'plugin'" in errors
    assert "Package path does not exist for 'cli': packages/cli" in errors
    assert "default_package 'docs' not in packages" in errors


def test_developer_journal_uses_configured_rotation_limit(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    reins_root = repo_root / ".reins"
    workspace_root = reins_root / "workspace"
    workspace_root.mkdir(parents=True)
    (reins_root / "config.yaml").write_text(
        "max_journal_lines: 20\n",
        encoding="utf-8",
    )

    journal = DeveloperJournal(workspace_root, "peppa")
    journal.add_session(_make_entry(1, "A" * 200))
    journal.add_session(_make_entry(2, "B" * 200))

    developer_dir = workspace_root / "peppa"
    assert (developer_dir / "journal-1.md").exists()
    assert (developer_dir / "journal-2.md").exists()
