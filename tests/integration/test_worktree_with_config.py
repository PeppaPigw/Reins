from __future__ import annotations

import subprocess
from pathlib import Path

from reins.isolation.agent_registry import AgentRegistry
from reins.isolation.worktree_manager import WorktreeManager
from reins.kernel.event.journal import EventJournal


def _init_git_repo(repo_root: Path) -> str:
    subprocess.run(["git", "init"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_root, check=True)
    (repo_root / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_root, check=True)
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


async def test_worktree_manager_runs_configured_copy_and_post_create(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    base_branch = _init_git_repo(repo_root)

    reins_dir = repo_root / ".reins"
    (reins_dir / "tasks" / "task-1").mkdir(parents=True)
    (reins_dir / ".developer").write_text("name=peppa\n", encoding="utf-8")
    (reins_dir / "worktree.yaml").write_text(
        """
worktree_dir: ../phase6-worktrees
copy:
  - .reins/.developer
post_create:
  - python -c "from pathlib import Path; Path('post-create.txt').write_text('ok', encoding='utf-8')"
verify:
  - test -f post-create.txt
""".strip(),
        encoding="utf-8",
    )

    journal = EventJournal(tmp_path / "journal.jsonl")
    registry = AgentRegistry(
        path=reins_dir / "registry.json",
        journal=journal,
        run_id="phase6-worktree",
    )
    manager = WorktreeManager(
        journal=journal,
        run_id="phase6-worktree",
        repo_root=repo_root,
        agent_registry=registry,
    )

    state = await manager.create_worktree_for_agent(
        agent_id="agent-1",
        task_id="task-1",
        branch_name="feat/task-1",
        base_branch=base_branch,
    )

    assert (state.worktree_path / ".reins" / ".developer").read_text(encoding="utf-8") == "name=peppa\n"
    assert (state.worktree_path / "post-create.txt").read_text(encoding="utf-8") == "ok"

    results = await manager.verify_worktree(state.worktree_id)
    assert results[0]["command"] == "test -f post-create.txt"
    assert results[0]["returncode"] == 0

    await manager.cleanup_agent_worktree(state.worktree_id, force=True)
