from __future__ import annotations

import subprocess
from pathlib import Path

from tests.unit.cli_helpers import create_repo, invoke, load_registry


def test_worktree_create_verify_and_cleanup_by_name(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path, git=True)
    (repo / ".reins" / ".developer").write_text("name=peppa\n", encoding="utf-8")
    (repo / ".reins" / "tasks" / "task-1").mkdir(parents=True)

    create_result = invoke(repo, monkeypatch, ["worktree", "create", "feature-lane", "--task", "task-1"])
    assert create_result.exit_code == 0

    worktree_path = repo / ".reins" / "worktrees" / "feature-lane"
    assert worktree_path.exists()

    registry = load_registry(repo)
    record = registry["agents"][0]
    assert record["agent_id"] == "feature-lane"

    verify_result = invoke(repo, monkeypatch, ["worktree", "verify", "feature-lane"])
    assert verify_result.exit_code == 0
    assert "directory exists" in verify_result.output

    cleanup_result = invoke(repo, monkeypatch, ["worktree", "cleanup", "feature-lane", "--force"])
    assert cleanup_result.exit_code == 0
    assert not worktree_path.exists()

    branch_result = subprocess.run(
        ["git", "branch", "--list", "feat/task-1"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert branch_result.stdout.strip() == ""


def test_worktree_list_verbose_and_prune(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path, git=True)
    (repo / ".reins" / ".developer").write_text("name=peppa\n", encoding="utf-8")
    (repo / ".reins" / "tasks" / "task-1").mkdir(parents=True)

    invoke(repo, monkeypatch, ["worktree", "create", "feature-lane", "--task", "task-1"])
    tracked_path = repo / ".reins" / "worktrees" / "feature-lane"
    (tracked_path / "notes.txt").write_text("dirty\n", encoding="utf-8")

    list_result = invoke(repo, monkeypatch, ["worktree", "list", "--verbose"])
    assert list_result.exit_code == 0
    assert "dirty" in list_result.output
    assert "feature-lane" in list_result.output

    orphan_path = repo.parent / "orphan-worktree"
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(orphan_path), "HEAD"],
        cwd=repo,
        check=True,
    )

    prune_result = invoke(repo, monkeypatch, ["worktree", "prune", "--all"])
    assert prune_result.exit_code == 0
    assert not orphan_path.exists()
