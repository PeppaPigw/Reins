from __future__ import annotations

import asyncio
import subprocess
from datetime import UTC, timedelta, datetime
import shutil

import pytest

from reins.cli import utils
from reins.isolation.agent_registry import AgentRegistry
from reins.isolation.worktree_config import (
    WorktreeConfigError,
    WorktreeTemplateConfig,
    load_worktree_config,
    save_worktree_config,
)
from reins.isolation.types import MergeStrategy
from reins.isolation.worktree_manager import WorktreeManager
from reins.task.manager import TaskManager
from reins.task.projection import TaskContextProjection
from tests.integration.helpers import (
    assert_event_types_in_order,
    create_test_task,
    load_run_events,
    simulate_agent_work,
    write_worktree_config,
)


@pytest.mark.asyncio
async def test_worktree_parallel_execution_integration(integration_harness) -> None:
    repo_root = integration_harness.repo_root
    base_branch = (
        subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
    )
    (repo_root / ".reins" / ".developer").write_text("peppa\n", encoding="utf-8")
    write_worktree_config(
        repo_root,
        post_create=["test -f .reins/.developer"],
        verify=["test -f .reins/.developer"],
    )

    run_id = "phase5-worktree"
    journal = utils.get_journal(repo_root)
    projection = TaskContextProjection()
    TaskManager(journal, projection, run_id=run_id)
    registry = AgentRegistry(
        path=repo_root / ".reins" / "registry.json",
        journal=journal,
        run_id=run_id,
    )
    worktree_manager = WorktreeManager(
        journal=journal,
        run_id=run_id,
        repo_root=repo_root,
        agent_registry=registry,
    )

    task_ids = []
    for idx in range(3):
        task_id = await create_test_task(
            repo_root,
            f"Parallel task {idx + 1}",
            journal=journal,
            projection=projection,
            run_id=run_id,
        )
        task_ids.append(task_id)

    states = await asyncio.gather(
        *[
            worktree_manager.create_worktree_for_agent(
                agent_id=f"agent-{idx + 1}",
                task_id=task_id,
                branch_name=f"feat/{task_id}",
                base_branch=base_branch,
            )
            for idx, task_id in enumerate(task_ids)
        ]
    )

    assert len(states) == 3
    assert len({state.worktree_id for state in states}) == 3
    assert len({state.worktree_path for state in states}) == 3

    for idx, state in enumerate(states):
        assert (state.worktree_path / ".reins" / ".developer").read_text(encoding="utf-8") == "peppa\n"
        assert (
            (state.worktree_path / ".reins" / ".current-task").read_text(encoding="utf-8").strip()
            == f"tasks/{task_ids[idx]}"
        )
        assert (
            subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=state.worktree_path,
                capture_output=True,
                text=True,
                check=True,
            )
            .stdout.strip()
            == f"feat/{task_ids[idx]}"
        )
        record = await registry.get(f"agent-{idx + 1}")
        assert record is not None
        assert record.task_id == task_ids[idx]
        await simulate_agent_work(
            state.worktree_path,
            file_name=f"agent-{idx + 1}.txt",
            content=f"worktree {idx + 1}\n",
        )

    verify_results = await asyncio.gather(
        *(worktree_manager.verify_worktree(state.worktree_id) for state in states)
    )
    assert all(result[0]["returncode"] == 0 for result in verify_results)
    assert len(await registry.list_by_status("verified")) == 3

    created_files = [
        (state.worktree_path / f"agent-{idx + 1}.txt").read_text(encoding="utf-8").strip()
        for idx, state in enumerate(states)
    ]
    assert created_files == ["worktree 1", "worktree 2", "worktree 3"]
    assert not (repo_root / "agent-1.txt").exists()

    await asyncio.gather(
        *[
            worktree_manager.cleanup_agent_worktree(
                state.worktree_id,
                force=True,
                removed_by="test",
                reason="integration cleanup",
            )
            for state in states
        ]
    )

    assert worktree_manager.list_worktrees() == []
    assert await registry.list_all() == []
    assert worktree_manager.detect_orphans() == []
    assert all(not state.worktree_path.exists() for state in states)

    events = await load_run_events(journal, run_id)
    assert_event_types_in_order(
        events,
        [
            "task.created",
            "worktree.created",
            "agent.registered",
            "worktree.verified",
            "agent.heartbeat_updated",
            "worktree.removed",
            "agent.unregistered",
        ],
    )
    assert sum(1 for event in events if event.type == "worktree.created") == 3
    assert sum(1 for event in events if event.type == "agent.registered") == 3
    assert sum(1 for event in events if event.type == "worktree.verified") == 3
    assert sum(1 for event in events if event.type == "worktree.removed") == 3


@pytest.mark.asyncio
async def test_worktree_merge_idle_and_orphan_cleanup(integration_harness) -> None:
    repo_root = integration_harness.repo_root
    base_branch = (
        subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
    )
    (repo_root / ".reins" / ".developer").write_text("peppa\n", encoding="utf-8")
    write_worktree_config(repo_root)

    run_id = "phase5-worktree-maintenance"
    journal = utils.get_journal(repo_root)
    projection = TaskContextProjection()
    registry = AgentRegistry(
        path=repo_root / ".reins" / "registry.json",
        journal=journal,
        run_id=run_id,
    )
    worktree_manager = WorktreeManager(
        journal=journal,
        run_id=run_id,
        repo_root=repo_root,
        agent_registry=registry,
    )

    merge_task_id = await create_test_task(
        repo_root,
        "Merge task",
        journal=journal,
        projection=projection,
        run_id=run_id,
    )
    merge_state = await worktree_manager.create_worktree_for_agent(
        agent_id="merge-agent",
        task_id=merge_task_id,
        branch_name=f"feat/{merge_task_id}",
        base_branch=base_branch,
    )
    merged_file = merge_state.worktree_path / "README.md"
    merged_file.write_text("# Test Repo\nmerged change\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=merge_state.worktree_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "worktree change"],
        cwd=merge_state.worktree_path,
        check=True,
    )

    commit_sha = await worktree_manager.merge_worktree(
        merge_state.worktree_id,
        MergeStrategy(strategy="merge", target_branch=base_branch),
        merged_by="test",
    )
    assert commit_sha is not None
    assert "merged change" in (repo_root / "README.md").read_text(encoding="utf-8")

    idle_task_id = await create_test_task(
        repo_root,
        "Idle task",
        journal=journal,
        projection=projection,
        run_id=run_id,
    )
    idle_state = await worktree_manager.create_worktree_for_agent(
        agent_id="idle-agent",
        task_id=idle_task_id,
        branch_name=f"feat/{idle_task_id}",
        base_branch=base_branch,
    )
    shutil.rmtree(idle_state.worktree_path / ".reins", ignore_errors=True)
    shutil.rmtree(idle_state.worktree_path / ".trellis", ignore_errors=True)
    idle_state.last_activity = datetime.now(UTC) - timedelta(hours=2)
    cleaned_idle = await worktree_manager.cleanup_idle(idle_threshold_seconds=1)
    assert idle_state.worktree_id in cleaned_idle

    orphan_path = repo_root.parent / "phase5-orphan-worktree"
    if orphan_path.exists():
        subprocess.run(["git", "worktree", "remove", str(orphan_path), "--force"], cwd=repo_root, check=True)
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(orphan_path), "HEAD"],
        cwd=repo_root,
        check=True,
    )
    assert orphan_path in worktree_manager.detect_orphans()
    cleaned_orphans = await worktree_manager.cleanup_orphans(force=True)
    assert orphan_path in cleaned_orphans
    assert not orphan_path.exists()

    await worktree_manager.cleanup_agent_worktree(
        merge_state.worktree_id,
        force=True,
        removed_by="test",
        reason="post-merge cleanup",
    )


def test_worktree_config_round_trip_and_validation(integration_harness) -> None:
    repo_root = integration_harness.repo_root
    reins_config = repo_root / ".reins" / "worktree.yaml"
    trellis_config = repo_root / ".trellis" / "worktree.yaml"
    reins_config.unlink(missing_ok=True)
    trellis_config.unlink(missing_ok=True)

    default_config = load_worktree_config(repo_root)
    assert default_config.copy == [".reins/.developer"]
    assert default_config.post_create == []
    assert default_config.verify == []

    saved_default = save_worktree_config(default_config, repo_root=repo_root)
    assert saved_default == reins_config.resolve()
    reloaded_default = load_worktree_config(repo_root)
    assert reloaded_default.worktree_dir == default_config.worktree_dir
    assert reloaded_default.copy == default_config.copy

    reins_config.unlink()
    custom_config = WorktreeTemplateConfig(
        worktree_dir=(repo_root / ".worktrees").resolve(),
        copy=[".reins/.developer", ".reins/.developer"],
        post_create=["echo setup"],
        verify=["test -f .reins/.developer"],
    )
    saved_custom = save_worktree_config(
        custom_config,
        repo_root=repo_root,
        path=trellis_config,
    )
    assert saved_custom == trellis_config.resolve()
    reloaded_custom = load_worktree_config(repo_root)
    assert reloaded_custom.source_path == trellis_config.resolve()
    assert reloaded_custom.worktree_dir == custom_config.worktree_dir
    assert reloaded_custom.post_create == ["echo setup"]
    assert reloaded_custom.verify == ["test -f .reins/.developer"]

    reins_config.write_text("copy:\n  - 1\n", encoding="utf-8")
    with pytest.raises(WorktreeConfigError):
        load_worktree_config(repo_root)
