from __future__ import annotations

import asyncio
import subprocess

import pytest

from reins.cli import utils
from reins.kernel.intent.envelope import CommandProposal, IntentEnvelope
from reins.task.context_jsonl import ContextJSONL
from tests.integration.helpers import (
    assert_event_types_in_order,
    build_orchestrator_bundle,
    ensure_base_specs,
)


@pytest.mark.asyncio
async def test_full_workflow_integration(integration_harness, tmp_path) -> None:
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

    assert (await asyncio.to_thread(integration_harness.invoke, ["developer", "init", "peppa"])).exit_code == 0
    assert (
        (
            await asyncio.to_thread(
                integration_harness.invoke,
                ["spec", "init", "--package", "cli", "--layers", "commands"],
            )
        )
        .exit_code
        == 0
    )
    ensure_base_specs(repo_root, package="cli", layers=("commands",))
    utils.write_developer_identity(repo_root, "peppa")
    (repo_root / ".reins" / "worktree.yaml").write_text(
        "worktree_dir: ../full-worktrees\ncopy:\n  - .reins/.developer\nverify:\n  - test -f .reins/.developer\n",
        encoding="utf-8",
    )

    create = await asyncio.to_thread(
        integration_harness.invoke,
        [
            "task",
            "create",
            "Run the full workflow",
            "--type",
            "backend",
            "--priority",
            "P0",
            "--package",
            "cli",
            "--prd",
            "Exercise the complete Phase 5 workflow end-to-end.",
            "--acceptance",
            "Workflow runs without errors",
        ],
    )
    assert create.exit_code == 0
    task_id = integration_harness.latest_task_id()

    assert (
        await asyncio.to_thread(integration_harness.invoke, ["task", "init-context", task_id, "backend"])
    ).exit_code == 0
    assert (
        (
            await asyncio.to_thread(
                integration_harness.invoke,
                ["worktree", "create", "agent-full", task_id, "--branch", f"feat/{task_id}", "--base", base_branch],
            )
        ).exit_code
        == 0
    )

    worktree_manager = utils.hydrate_worktree_manager(repo_root, "workflow-inspect")
    states = worktree_manager.list_worktrees()
    assert len(states) == 1
    worktree_state = states[0]

    context_messages = ContextJSONL.read_messages(
        worktree_state.worktree_path / ".reins" / "tasks" / task_id / "implement.jsonl"
    )
    assert context_messages
    assert any("Pre-Development Checklist" in message.content for message in context_messages)

    bundle = build_orchestrator_bundle(tmp_path, repo_root=repo_root, run_id="full-workflow")
    orchestrator = bundle.orchestrator
    await orchestrator.intake(IntentEnvelope(run_id="full-workflow", objective="Execute workflow inside worktree"))
    await orchestrator.route()

    read_context = await orchestrator.process_proposal(
        CommandProposal(
            run_id="full-workflow",
            source="model",
            kind="fs.read",
            args={
                "root": str(worktree_state.worktree_path),
                "path": f".reins/tasks/{task_id}/implement.jsonl",
            },
        )
    )
    assert read_context["granted"] is True
    assert "Pre-Development Checklist" in read_context["observation"]["stdout"]

    write_result = await orchestrator.process_proposal(
        CommandProposal(
            run_id="full-workflow",
            source="model",
            kind="fs.write.workspace",
            args={
                "root": str(worktree_state.worktree_path),
                "path": "src/result.txt",
                "content": "workflow complete\n",
            },
        )
    )
    assert write_result["granted"] is True
    assert (worktree_state.worktree_path / "src" / "result.txt").exists()

    verify_result = await orchestrator.process_proposal(
        CommandProposal(
            run_id="full-workflow",
            source="model",
            kind="exec.shell.sandboxed",
            args={"cmd": "test -f src/result.txt && echo ok", "cwd": str(worktree_state.worktree_path)},
        )
    )
    assert verify_result["executed"] is True
    assert "ok" in verify_result["observation"]["stdout"]

    await orchestrator.complete()
    checkpoint_id = await orchestrator.dehydrate()
    snapshot = await bundle.snapshots.load("full-workflow", orchestrator.state.snapshot_id)
    assert snapshot.run_id == "full-workflow"
    assert snapshot.active_grants
    assert checkpoint_id == orchestrator.state.last_checkpoint_id

    assert (
        await asyncio.to_thread(integration_harness.invoke, ["task", "start", task_id, "--assignee", "peppa"])
    ).exit_code == 0
    assert (
        await asyncio.to_thread(integration_harness.invoke, ["task", "finish", task_id, "--note", "Full workflow done"])
    ).exit_code == 0
    assert (
        await asyncio.to_thread(integration_harness.invoke, ["task", "archive", task_id, "--reason", "E2E covered"])
    ).exit_code == 0
    assert (
        await asyncio.to_thread(
            integration_harness.invoke,
            ["worktree", "cleanup", worktree_state.worktree_id, "--force"],
        )
    ).exit_code == 0

    final_manager = utils.hydrate_worktree_manager(repo_root, "workflow-inspect-final")
    assert final_manager.list_worktrees() == []

    events = integration_harness.load_events()
    assert_event_types_in_order(
        events,
        [
            "developer.initialized",
            "spec.initialized",
            "task.created",
            "task.context_initialized",
            "worktree.created",
            "command.executed",
            "run.completed",
            "run.dehydrated",
            "task.completed",
            "task.archived",
            "worktree.removed",
        ],
    )
