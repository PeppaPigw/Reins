from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from reins.context.compiler import ContextCompiler
from reins.execution.dispatcher import ExecutionDispatcher
from reins.kernel.event.journal import EventJournal
from reins.kernel.intent.envelope import CommandProposal, IntentEnvelope
from reins.kernel.orchestrator import RunOrchestrator
from reins.memory.checkpoint import CheckpointStore
from reins.policy.approval.ledger import ApprovalLedger
from reins.policy.engine import PolicyEngine
from reins.kernel.snapshot.store import SnapshotStore


def _make_orchestrator(tmp_path: Path) -> tuple[RunOrchestrator, ApprovalLedger]:
    journal = EventJournal(tmp_path / "journal.jsonl")
    snapshots = SnapshotStore(tmp_path / "snapshots")
    checkpoints = CheckpointStore(tmp_path / "checkpoints")
    policy = PolicyEngine()
    context = ContextCompiler()
    dispatcher = ExecutionDispatcher()
    approvals = ApprovalLedger(tmp_path / "approvals")
    orchestrator = RunOrchestrator(
        journal,
        snapshots,
        checkpoints,
        policy,
        context,
        approval_ledger=approvals,
        dispatcher=dispatcher,
    )
    return orchestrator, approvals


@pytest.mark.asyncio
async def test_orchestrator_accepts_delegated_approval(tmp_path):
    orchestrator, approvals = _make_orchestrator(tmp_path)
    await orchestrator.intake(IntentEnvelope(run_id="run-1", objective="test"))
    await orchestrator.route()

    proposal = CommandProposal(
        run_id="run-1",
        source="model",
        kind="exec.shell.network",
        args={"cmd": "echo delegated", "cwd": str(tmp_path)},
    )

    first_result = await orchestrator.process_proposal(proposal)
    assert first_result["needs_approval"] is True

    delegation = await approvals.delegate(
        from_actor="human",
        to_actor="senior-agent",
        scope=["exec.shell.network"],
        resource_scope=[str(tmp_path)],
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    grant = await orchestrator.approve(
        first_result["request_id"],
        granted_by="senior-agent",
    )

    assert grant is not None
    assert grant.delegation_id == delegation.delegation_id

    second_result = await orchestrator.process_proposal(proposal)
    assert second_result["granted"] is True
    assert second_result["executed"] is True
    assert orchestrator.state.active_grants[0].issued_to == "senior-agent"

    audit_entries = approvals.audit(actor="senior-agent", kind="request.approved")
    assert len(audit_entries) == 1
    assert audit_entries[0].delegation_id == delegation.delegation_id


@pytest.mark.asyncio
async def test_orchestrator_rejects_delegated_approval_outside_scope(tmp_path):
    orchestrator, approvals = _make_orchestrator(tmp_path)
    await orchestrator.intake(IntentEnvelope(run_id="run-2", objective="test"))
    await orchestrator.route()

    proposal = CommandProposal(
        run_id="run-2",
        source="model",
        kind="exec.shell.network",
        args={"cmd": "echo blocked", "cwd": str(tmp_path)},
    )

    first_result = await orchestrator.process_proposal(proposal)
    assert first_result["needs_approval"] is True

    await approvals.delegate(
        from_actor="human",
        to_actor="limited-agent",
        scope=["git.push"],
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    with pytest.raises(PermissionError):
        await orchestrator.approve(
            first_result["request_id"],
            granted_by="limited-agent",
        )

    assert orchestrator.state.pending_approvals == [first_result["request_id"]]
    assert approvals.pending[0].request_id == first_result["request_id"]
