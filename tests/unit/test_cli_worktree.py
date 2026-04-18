from __future__ import annotations

import subprocess
from pathlib import Path

from tests.unit.cli_helpers import create_repo, current_branch, invoke, load_registry


def test_worktree_commands(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path, git=True)
    base_branch = current_branch(repo)

    (repo / ".reins" / ".developer").write_text("name=peppa\n", encoding="utf-8")
    (repo / ".reins" / "tasks" / "task-1").mkdir(parents=True)
    (repo / ".reins" / "worktree.yaml").write_text(
        "worktree_dir: ../worktrees\ncopy:\n  - .reins/.developer\nverify:\n  - test -f .reins/.developer\n",
        encoding="utf-8",
    )

    create_result = invoke(
        repo,
        monkeypatch,
        ["worktree", "create", "agent-1", "task-1", "--branch", "feat/task-1", "--base", base_branch],
    )
    assert create_result.exit_code == 0

    registry = load_registry(repo)
    assert len(registry["agents"]) == 1
    record = registry["agents"][0]
    worktree_id = record["worktree_id"]

    list_result = invoke(repo, monkeypatch, ["worktree", "list"])
    assert list_result.exit_code == 0
    assert worktree_id in list_result.output

    verify_result = invoke(repo, monkeypatch, ["worktree", "verify", worktree_id])
    assert verify_result.exit_code == 0
    assert "test -f .reins/.developer" in verify_result.output

    orphan_path = repo.parent / "orphan-worktree"
    subprocess.run(
        ["git", "worktree", "add", str(orphan_path), "-b", "orphan-branch", base_branch],
        cwd=repo,
        check=True,
    )
    cleanup_orphans = invoke(repo, monkeypatch, ["worktree", "cleanup-orphans", "--force"])
    assert cleanup_orphans.exit_code == 0
    assert not orphan_path.exists()

    cleanup = invoke(repo, monkeypatch, ["worktree", "cleanup", worktree_id, "--force"])
    assert cleanup.exit_code == 0
