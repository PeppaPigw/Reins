from __future__ import annotations

import pytest

from reins.execution.dispatcher import ExecutionDispatcher
from reins.kernel.intent.envelope import CommandProposal, IntentEnvelope
from reins.kernel.orchestrator import RunOrchestrator
from reins.kernel.snapshot.store import SnapshotStore
from tests.integration.helpers import build_orchestrator_bundle, load_run_events


@pytest.mark.asyncio
async def test_checkpoint_resume_integration(tmp_path) -> None:
    bundle = build_orchestrator_bundle(tmp_path, run_id="checkpoint-run")
    repo_root = bundle.repo_root
    (repo_root / "state.txt").write_text("checkpoint data\n", encoding="utf-8")

    orchestrator = bundle.orchestrator
    await orchestrator.intake(IntentEnvelope(run_id="checkpoint-run", objective="Resume from checkpoint"))
    await orchestrator.route()

    task_id = await orchestrator.create_task(
        title="Checkpoint task",
        task_type="backend",
        prd_content="Preserve active task and handles across hydrate.",
        acceptance_criteria=["Hydration restores run state"],
    )
    await orchestrator.start_task(task_id, assignee="peppa")

    proposal = CommandProposal(
        run_id="checkpoint-run",
        source="model",
        kind="fs.read",
        args={"root": str(repo_root), "path": "state.txt"},
    )
    first = await orchestrator.process_proposal(proposal)
    assert first["granted"] is True
    assert first["executed"] is True

    checkpoint_id = await orchestrator.dehydrate()
    manifest = await bundle.checkpoints.load("checkpoint-run", checkpoint_id)
    assert manifest.checkpoint_id == checkpoint_id
    assert manifest.snapshot_id is not None
    assert manifest.revalidation_steps
    latest_snapshot = await bundle.snapshots.latest("checkpoint-run")
    assert latest_snapshot is not None
    assert latest_snapshot.snapshot_id == manifest.snapshot_id
    assert latest_snapshot.active_task_id == task_id

    empty_snapshots = SnapshotStore(tmp_path / "empty-snapshots")
    assert await empty_snapshots.latest("missing-run") is None

    events_before = await load_run_events(bundle.journal, "checkpoint-run")
    handle_open_count_before = sum(
        1 for event in events_before if event.type == "adapter.handle_opened"
    )
    assert handle_open_count_before == 1

    restored = RunOrchestrator(
        journal=bundle.journal,
        snapshot_store=bundle.snapshots,
        checkpoint_store=bundle.checkpoints,
        policy_engine=bundle.policy,
        context_compiler=bundle.context,
        approval_ledger=bundle.approvals,
        dispatcher=ExecutionDispatcher(),
        task_manager=bundle.task_manager,
        task_projection=bundle.task_projection,
    )
    state = await restored.hydrate(checkpoint_id)
    assert state.last_checkpoint_id == checkpoint_id
    assert state.active_task_id == task_id
    assert any(grant.capability == "fs.read" for grant in state.active_grants)
    assert any(handle.adapter_kind == "fs" for handle in state.open_handles)

    second = await restored.process_proposal(proposal)
    assert second["granted"] is True
    assert second["executed"] is True

    events_after = await load_run_events(bundle.journal, "checkpoint-run")
    handle_open_count_after = sum(
        1 for event in events_after if event.type == "adapter.handle_opened"
    )
    assert handle_open_count_after == handle_open_count_before
    assert any(event.type == "run.dehydrated" for event in events_after)
    assert any(event.type == "run.hydrated" for event in events_after)
