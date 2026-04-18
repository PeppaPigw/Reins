from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from reins.isolation.agent_registry import AgentRegistry
from reins.isolation.types import MergeStrategy, WorktreeConfig, WorktreeState
from reins.isolation.worktree_manager import WorktreeError, WorktreeManager
from reins.kernel.event.journal import EventJournal


def _make_config(tmp_path: Path, **overrides: object) -> WorktreeConfig:
    defaults: dict[str, object] = {
        "worktree_base_dir": tmp_path / "worktrees",
        "worktree_name": "agent-worktree",
        "branch_name": "feat/test",
        "base_branch": "main",
        "create_branch": True,
        "copy_files": [],
        "post_create_commands": [],
        "verify_commands": [],
    }
    defaults.update(overrides)
    return WorktreeConfig(**defaults)


def _make_state(tmp_path: Path, *, worktree_id: str = "wt-1", agent_id: str = "agent-1") -> WorktreeState:
    config = _make_config(tmp_path)
    path = tmp_path / worktree_id
    path.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    return WorktreeState(
        worktree_id=worktree_id,
        worktree_path=path,
        branch_name=config.branch_name,
        base_branch=config.base_branch,
        agent_id=agent_id,
        task_id="task-1",
        created_at=now,
        config=config,
        last_activity=now,
    )


@pytest.mark.asyncio
async def test_create_worktree_cleans_up_on_post_create_failure(tmp_path: Path) -> None:
    manager = WorktreeManager(
        journal=EventJournal(tmp_path / "journal.jsonl"),
        run_id="run-1",
        repo_root=tmp_path / "repo",
    )
    manager._repo_root.mkdir()
    config = _make_config(tmp_path, post_create_commands=["fail-now"])
    cleanup_calls: list[tuple[Path, bool]] = []

    async def fake_add(path: Path, branch: str, base_branch: str, create_branch: bool) -> None:
        path.mkdir(parents=True, exist_ok=True)

    async def fake_remove(path: Path, force: bool = False) -> None:
        cleanup_calls.append((path, force))

    async def fake_run(command: str, cwd: Path) -> str:
        if command == "fail-now":
            raise WorktreeError("boom")
        return ""

    manager._git_worktree_add = fake_add  # type: ignore[method-assign]
    manager._git_worktree_remove = fake_remove  # type: ignore[method-assign]
    manager._run_command = fake_run  # type: ignore[method-assign]

    with pytest.raises(WorktreeError, match="Failed to create worktree"):
        await manager.create_worktree(agent_id="agent-1", task_id="task-1", config=config)

    assert cleanup_calls == [(config.worktree_base_dir / config.worktree_name, True)]


@pytest.mark.asyncio
async def test_create_worktree_for_agent_cleans_up_if_marker_write_fails(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".reins").mkdir()
    (repo_root / ".reins" / "worktree.yaml").write_text("worktree_dir: ../wt\n", encoding="utf-8")
    manager = WorktreeManager(
        journal=EventJournal(tmp_path / "journal.jsonl"),
        run_id="run-1",
        repo_root=repo_root,
    )
    state = _make_state(tmp_path, worktree_id="agent-worktree")
    removed: list[str] = []

    async def fake_create_worktree(agent_id: str, task_id: str | None, config: WorktreeConfig) -> WorktreeState:
        return state

    async def fake_write_current_task_files(worktree_path: Path, task_id: str) -> None:
        raise OSError("marker write failed")

    async def fake_remove_worktree(
        worktree_id: str,
        force: bool = False,
        removed_by: str = "system",
        reason: str | None = None,
    ) -> None:
        removed.append(worktree_id)

    manager.create_worktree = fake_create_worktree  # type: ignore[method-assign]
    manager._write_current_task_files = fake_write_current_task_files  # type: ignore[method-assign]
    manager.remove_worktree = fake_remove_worktree  # type: ignore[method-assign]

    with pytest.raises(WorktreeError, match="Failed to create agent worktree"):
        await manager.create_worktree_for_agent(
            agent_id="agent-1",
            task_id="task-1",
            branch_name="feat/test",
            base_branch="main",
        )

    assert removed == ["agent-worktree"]


@pytest.mark.asyncio
async def test_verify_worktree_failure_updates_registry_status(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
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
    state = _make_state(tmp_path, agent_id="agent-1")
    state.config.verify_commands.append("fail-check")
    manager._worktrees[state.worktree_id] = state
    await registry.register(
        agent_id="agent-1",
        worktree_id=state.worktree_id,
        task_id="task-1",
        status="running",
    )

    async def fake_capture(command: str, cwd: Path) -> dict[str, object]:
        return {
            "command": command,
            "returncode": 1,
            "stdout": "",
            "stderr": "boom",
        }

    manager._run_command_capture = fake_capture  # type: ignore[method-assign]

    with pytest.raises(WorktreeError, match="Verification failed"):
        await manager.verify_worktree(state.worktree_id)

    updated = await registry.get("agent-1")
    assert updated is not None
    assert updated.status == "verify_failed"

    with pytest.raises(WorktreeError, match="Worktree not found"):
        await manager.verify_worktree("missing")


@pytest.mark.asyncio
async def test_remove_worktree_errors_and_cleanup_helpers(tmp_path: Path) -> None:
    manager = WorktreeManager(
        journal=EventJournal(tmp_path / "journal.jsonl"),
        run_id="run-1",
        repo_root=tmp_path / "repo",
    )
    manager._repo_root.mkdir()

    with pytest.raises(WorktreeError, match="Worktree not found"):
        await manager.remove_worktree("missing")

    state = _make_state(tmp_path)
    manager._worktrees[state.worktree_id] = state

    async def fake_remove(path: Path, force: bool = False) -> None:
        raise WorktreeError("cannot remove")

    manager._git_worktree_remove = fake_remove  # type: ignore[method-assign]

    with pytest.raises(WorktreeError, match="Failed to remove worktree"):
        await manager.remove_worktree(state.worktree_id)


@pytest.mark.asyncio
async def test_merge_worktree_strategies_and_unknown_strategy(tmp_path: Path) -> None:
    manager = WorktreeManager(
        journal=EventJournal(tmp_path / "journal.jsonl"),
        run_id="run-1",
        repo_root=tmp_path / "repo",
    )
    manager._repo_root.mkdir()
    state = _make_state(tmp_path)
    manager._worktrees[state.worktree_id] = state

    async def fake_checkout(branch: str, cwd: Path) -> None:
        return None

    async def fake_merge(branch: str, cwd: Path) -> str:
        return "merge-sha"

    async def fake_rebase(branch: str, cwd: Path) -> str:
        return "rebase-sha"

    async def fake_squash(branch: str, cwd: Path) -> str:
        return "squash-sha"

    manager._git_checkout = fake_checkout  # type: ignore[method-assign]
    manager._git_merge = fake_merge  # type: ignore[method-assign]
    manager._git_rebase = fake_rebase  # type: ignore[method-assign]
    manager._git_merge_squash = fake_squash  # type: ignore[method-assign]

    assert await manager.merge_worktree(state.worktree_id, MergeStrategy("merge", "main")) == "merge-sha"
    assert await manager.merge_worktree(state.worktree_id, MergeStrategy("rebase", "main")) == "rebase-sha"
    assert await manager.merge_worktree(state.worktree_id, MergeStrategy("squash", "main")) == "squash-sha"

    with pytest.raises(WorktreeError, match="Unknown merge strategy"):
        await manager.merge_worktree(state.worktree_id, MergeStrategy("nope", "main"))


def test_detect_orphans_parses_git_output_and_handles_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    manager = WorktreeManager(
        journal=EventJournal(tmp_path / "journal.jsonl"),
        run_id="run-1",
        repo_root=repo_root,
    )
    tracked = _make_state(tmp_path, worktree_id="tracked")
    manager._worktrees[tracked.worktree_id] = tracked
    orphan = tmp_path / "orphan"

    class Result:
        stdout = (
            f"worktree {repo_root}\n"
            f"worktree {tracked.worktree_path}\n"
            f"worktree {orphan}\n"
        )

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: Result())
    assert manager.detect_orphans() == [orphan]

    def raise_called_process_error(*args: object, **kwargs: object) -> object:
        raise subprocess.CalledProcessError(1, "git")

    monkeypatch.setattr(subprocess, "run", raise_called_process_error)
    assert manager.detect_orphans() == []


@pytest.mark.asyncio
async def test_cleanup_idle_orphans_and_helper_methods(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    manager = WorktreeManager(
        journal=EventJournal(tmp_path / "journal.jsonl"),
        run_id="run-1",
        repo_root=repo_root,
    )
    idle = _make_state(tmp_path, worktree_id="idle")
    idle.last_activity = datetime.now(UTC) - timedelta(hours=2)
    failing_idle = _make_state(tmp_path, worktree_id="failing-idle")
    failing_idle.last_activity = datetime.now(UTC) - timedelta(hours=2)
    manager._worktrees[idle.worktree_id] = idle
    manager._worktrees[failing_idle.worktree_id] = failing_idle
    removed: list[str] = []

    async def fake_remove_worktree(
        worktree_id: str,
        force: bool = False,
        removed_by: str = "system",
        reason: str | None = None,
    ) -> None:
        if worktree_id == "failing-idle":
            raise WorktreeError("busy")
        removed.append(worktree_id)
        manager._worktrees.pop(worktree_id, None)

    manager.remove_worktree = fake_remove_worktree  # type: ignore[method-assign]

    cleaned = await manager.cleanup_idle(idle_threshold_seconds=60)
    assert cleaned == ["idle"]

    async def fake_git_remove(path: Path, force: bool = False) -> None:
        if path.name == "bad-orphan":
            raise WorktreeError("cannot remove")

    manager.detect_orphans = lambda: [tmp_path / "good-orphan", tmp_path / "bad-orphan"]  # type: ignore[method-assign]
    manager._git_worktree_remove = fake_git_remove  # type: ignore[method-assign]

    orphan_results = await manager.cleanup_orphans(force=True)
    assert orphan_results == [tmp_path / "good-orphan"]

    commands: list[str] = []

    async def fake_run(command: str, cwd: Path) -> str:
        commands.append(command)
        if command == "git rev-parse HEAD":
            return "abc123\n"
        return ""

    manager._run_command = fake_run  # type: ignore[method-assign]

    await manager._git_worktree_add(tmp_path / "branch-worktree", "feat/demo", "main", True)
    await manager._git_worktree_add(tmp_path / "existing-branch", "feat/demo", "main", False)
    await manager._git_checkout("main", repo_root)
    assert await manager._git_merge("feat/demo", repo_root) == "abc123"
    assert await manager._git_rebase("feat/demo", repo_root) == "abc123"
    assert await manager._git_merge_squash("feat/demo", repo_root) == "abc123"
    assert commands[0].startswith("git worktree add -b feat/demo")
    assert "existing-branch feat/demo" in commands[1]

    async def fake_run_error(command: str, cwd: Path) -> str:
        raise RuntimeError("boom")

    manager._run_command = fake_run_error  # type: ignore[method-assign]
    assert await manager._get_current_commit(repo_root) is None

    source = tmp_path / "source.txt"
    destination = tmp_path / "copied" / "source.txt"
    source.write_text("copy-me\n", encoding="utf-8")
    await manager._copy_file(source, destination)
    assert destination.read_text(encoding="utf-8") == "copy-me\n"
    await manager._copy_file(tmp_path / "missing.txt", tmp_path / "copied" / "missing.txt")

    capture = await manager._run_command_capture("python -c \"print('hello')\"", cwd=repo_root)
    assert capture["returncode"] == 0
    assert capture["stdout"].strip() == "hello"

    no_registry_manager = WorktreeManager(
        journal=EventJournal(tmp_path / "journal-2.jsonl"),
        run_id="run-2",
        repo_root=repo_root,
    )
    assert no_registry_manager._get_agent_registry(create_default=False) is None
    assert no_registry_manager._get_agent_registry(create_default=True) is not None
    assert no_registry_manager._default_worktree_name("agent 1", "task 1").startswith("task-1-agent-1")

    (repo_root / ".trellis" / "tasks" / "task-1").mkdir(parents=True)
    assert no_registry_manager._resolve_task_pointer("task-1") == ".trellis/tasks/task-1"
    assert no_registry_manager._resolve_task_pointer("missing") == ".reins/tasks/missing"
