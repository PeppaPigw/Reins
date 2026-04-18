from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

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


@pytest.mark.asyncio
async def test_create_worktree_for_agent_uses_yaml_config_and_registry(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    base_branch = _init_git_repo(repo_root)

    (repo_root / ".reins").mkdir()
    (repo_root / ".reins" / ".developer").write_text("agent-name\n", encoding="utf-8")
    (repo_root / ".reins" / "tasks").mkdir()
    (repo_root / ".reins" / "tasks" / "task-1").mkdir()
    (repo_root / ".reins" / "worktree.yaml").write_text(
        """
worktree_dir: ../parallel-worktrees
copy:
  - .reins/.developer
post_create:
  - python -V
verify:
  - test -f .reins/.developer
""".strip(),
        encoding="utf-8",
    )

    journal = EventJournal(tmp_path / "journal.jsonl")
    registry = AgentRegistry(
        path=repo_root / ".reins" / "registry.json",
        journal=journal,
        run_id="run-1",
    )
    manager = WorktreeManager(
        journal=journal,
        run_id="run-1",
        repo_root=repo_root,
        agent_registry=registry,
    )

    state = await manager.create_worktree_for_agent(
        agent_id="agent-1",
        task_id="task-1",
        branch_name="feat/task-1",
        base_branch=base_branch,
    )

    assert state.worktree_path.exists()
    assert (state.worktree_path / ".reins" / ".developer").read_text(encoding="utf-8") == "agent-name\n"
    assert (state.worktree_path / ".reins" / ".current-task").read_text(encoding="utf-8").strip() == "tasks/task-1"

    record = await registry.get("agent-1")
    assert record is not None
    assert record.worktree_id == state.worktree_id
    assert record.task_id == "task-1"

    verify_output = await manager.verify_worktree(state.worktree_id)
    assert verify_output[0]["command"] == "test -f .reins/.developer"
    assert verify_output[0]["returncode"] == 0

    await manager.cleanup_agent_worktree(
        state.worktree_id,
        force=True,
        removed_by="test",
        reason="cleanup",
    )

    assert await registry.get("agent-1") is None
    assert not state.worktree_path.exists()


@pytest.mark.asyncio
async def test_create_worktree_for_agent_supports_parallel_agents(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    base_branch = _init_git_repo(repo_root)

    (repo_root / ".reins").mkdir()
    (repo_root / ".reins" / ".developer").write_text("agent-name\n", encoding="utf-8")
    (repo_root / ".reins" / "tasks").mkdir()
    for task_id in ("task-1", "task-2"):
        (repo_root / ".reins" / "tasks" / task_id).mkdir()
    (repo_root / ".reins" / "worktree.yaml").write_text(
        "worktree_dir: ../parallel-worktrees\ncopy:\n  - .reins/.developer\n",
        encoding="utf-8",
    )

    journal = EventJournal(tmp_path / "journal.jsonl")
    registry = AgentRegistry(
        path=repo_root / ".reins" / "registry.json",
        journal=journal,
        run_id="run-1",
    )
    manager = WorktreeManager(
        journal=journal,
        run_id="run-1",
        repo_root=repo_root,
        agent_registry=registry,
    )

    states = await asyncio.gather(
        manager.create_worktree_for_agent(
            agent_id="agent-1",
            task_id="task-1",
            branch_name="feat/task-1",
            base_branch=base_branch,
        ),
        manager.create_worktree_for_agent(
            agent_id="agent-2",
            task_id="task-2",
            branch_name="feat/task-2",
            base_branch=base_branch,
        ),
    )

    assert len({state.worktree_id for state in states}) == 2
    assert len(await registry.list_by_status("running")) == 2

    for state in states:
        await manager.cleanup_agent_worktree(state.worktree_id, force=True)


@pytest.mark.asyncio
async def test_create_worktree_for_agent_cleans_up_after_post_create_failure(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    base_branch = _init_git_repo(repo_root)

    (repo_root / ".reins").mkdir()
    (repo_root / ".reins" / ".developer").write_text("agent-name\n", encoding="utf-8")
    (repo_root / ".reins" / "tasks").mkdir()
    (repo_root / ".reins" / "tasks" / "task-1").mkdir()
    (repo_root / ".reins" / "worktree.yaml").write_text(
        """
worktree_dir: ../parallel-worktrees
copy:
  - .reins/.developer
post_create:
  - python -c "raise SystemExit(1)"
""".strip(),
        encoding="utf-8",
    )

    journal = EventJournal(tmp_path / "journal.jsonl")
    registry = AgentRegistry(
        path=repo_root / ".reins" / "registry.json",
        journal=journal,
        run_id="run-1",
    )
    manager = WorktreeManager(
        journal=journal,
        run_id="run-1",
        repo_root=repo_root,
        agent_registry=registry,
    )

    with pytest.raises(Exception):
        await manager.create_worktree_for_agent(
            agent_id="agent-1",
            task_id="task-1",
            branch_name="feat/task-1",
            base_branch=base_branch,
        )

    assert await registry.get("agent-1") is None
    assert manager.list_worktrees() == []
