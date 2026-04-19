from __future__ import annotations

from pathlib import Path

from tests.unit.cli_helpers import create_repo, invoke


def test_worktree_cli_dirty_verify_and_forced_cleanup(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path, git=True)
    (repo / ".reins" / ".developer").write_text("name=peppa\n", encoding="utf-8")
    (repo / ".reins" / "tasks" / "task-1").mkdir(parents=True)

    create_result = invoke(repo, monkeypatch, ["worktree", "create", "feature-lane", "--task", "task-1"])
    assert create_result.exit_code == 0

    worktree_path = repo / ".reins" / "worktrees" / "feature-lane"
    (worktree_path / "dirty.txt").write_text("change\n", encoding="utf-8")

    verify_result = invoke(repo, monkeypatch, ["worktree", "verify", "feature-lane"])
    assert verify_result.exit_code == 1
    assert "working tree clean" in verify_result.output

    cleanup_result = invoke(repo, monkeypatch, ["worktree", "cleanup", "feature-lane"])
    assert cleanup_result.exit_code == 1
    assert "uncommitted changes" in cleanup_result.output

    forced_cleanup = invoke(repo, monkeypatch, ["worktree", "cleanup", "feature-lane", "--force"])
    assert forced_cleanup.exit_code == 0
    assert not worktree_path.exists()
