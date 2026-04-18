"""Tests for complete grant lifecycle: request → approve → grant → expire → re-request."""

import pytest
import time
from pathlib import Path

from reins.kernel.event.journal import EventJournal
from reins.kernel.intent.envelope import CommandProposal, IntentEnvelope
from reins.kernel.orchestrator import RunOrchestrator
from reins.kernel.snapshot.store import SnapshotStore
from reins.kernel.types import RiskTier
from reins.memory.checkpoint import CheckpointStore
from reins.policy.engine import PolicyEngine
from reins.context.compiler import ContextCompiler
from reins.execution.dispatcher import ExecutionDispatcher
from reins.policy.approval.ledger import ApprovalLedger


def _make_orchestrator(tmp_path: Path) -> RunOrchestrator:
    journal = EventJournal(tmp_path / "journal.jsonl")
    snapshots = SnapshotStore(tmp_path / "snapshots")
    checkpoints = CheckpointStore(tmp_path / "checkpoints")
    policy = PolicyEngine()
    context = ContextCompiler()
    dispatcher = ExecutionDispatcher()
    approval_ledger = ApprovalLedger(tmp_path / "approvals")
    return RunOrchestrator(
        journal,
        snapshots,
        checkpoints,
        policy,
        context,
        approval_ledger=approval_ledger,
        dispatcher=dispatcher,
    )


@pytest.mark.asyncio
async def test_grant_lifecycle_low_risk_auto_grant(tmp_path):
    """Low-risk capabilities (T0-T1) should auto-grant without approval."""
    orch = _make_orchestrator(tmp_path)
    await orch.intake(IntentEnvelope(run_id="test-run", objective="test"))
    await orch.route()

    # Create test file
    test_file = tmp_path / "test.txt"
    test_file.write_text("test content")

    # T0 capability - should auto-grant
    proposal = CommandProposal(
        run_id="test-run",
        source="model",
        kind="fs.read",
        args={"root": str(tmp_path), "path": "test.txt"},
    )

    result = await orch.process_proposal(proposal)

    # Should be granted and executed
    assert result["granted"] is True
    assert result["executed"] is True

    # Grant should be in active grants
    assert len(orch.state.active_grants) == 1
    grant = orch.state.active_grants[0]
    assert grant.capability == "fs.read"
    assert grant.issued_to == "model"


@pytest.mark.asyncio
async def test_grant_lifecycle_high_risk_requires_approval(tmp_path):
    """High-risk capabilities (T2-T3) should require approval."""
    orch = _make_orchestrator(tmp_path)
    await orch.intake(IntentEnvelope(run_id="test-run", objective="test"))
    await orch.route()

    # T2 capability - should require approval
    proposal = CommandProposal(
        run_id="test-run",
        source="model",
        kind="exec.shell.network",
        args={"cmd": "curl https://example.com", "cwd": str(tmp_path)},
    )

    result = await orch.process_proposal(proposal)

    # Should not be granted, should ask for approval
    assert result["granted"] is False
    assert result["needs_approval"] is True
    assert "request_id" in result

    # No grants should be active yet
    assert len(orch.state.active_grants) == 0
    # Should have pending approval
    assert len(orch.state.pending_approvals) == 1


@pytest.mark.asyncio
async def test_grant_lifecycle_approval_flow(tmp_path):
    """Test complete approval flow: request → approve → grant → execute."""
    orch = _make_orchestrator(tmp_path)
    await orch.intake(IntentEnvelope(run_id="test-run", objective="test"))
    await orch.route()

    # Request high-risk capability
    proposal = CommandProposal(
        run_id="test-run",
        source="model",
        kind="exec.shell.network",
        args={"cmd": "echo test", "cwd": str(tmp_path)},
    )

    result1 = await orch.process_proposal(proposal)
    assert result1["needs_approval"] is True
    request_id = result1["request_id"]

    # Approve the request
    grant = await orch.approve(request_id, granted_by="human")
    assert grant is not None
    assert grant.capability == "exec.shell.network"

    # Grant should now be active
    assert len(orch.state.active_grants) == 1

    # Re-submit the same proposal - should now be granted
    result2 = await orch.process_proposal(proposal)
    assert result2["granted"] is True
    assert result2["executed"] is True


@pytest.mark.asyncio
async def test_grant_lifecycle_rejection_flow(tmp_path):
    """Test rejection flow: request → reject → no grant."""
    orch = _make_orchestrator(tmp_path)
    await orch.intake(IntentEnvelope(run_id="test-run", objective="test"))
    await orch.route()

    # Request high-risk capability
    proposal = CommandProposal(
        run_id="test-run",
        source="model",
        kind="exec.shell.network",
        args={"cmd": "rm -rf /", "cwd": str(tmp_path)},
    )

    result1 = await orch.process_proposal(proposal)
    assert result1["needs_approval"] is True
    request_id = result1["request_id"]

    # Reject the request
    await orch.reject(request_id, reason="too dangerous", rejected_by="human")

    # No grants should be active
    assert len(orch.state.active_grants) == 0

    # Re-submit the same proposal - should still require approval
    result2 = await orch.process_proposal(proposal)
    assert result2["granted"] is False
    assert result2["needs_approval"] is True


@pytest.mark.asyncio
async def test_grant_lifecycle_expiration_and_reauth(tmp_path):
    """Test grant expiration and re-authentication flow."""
    orch = _make_orchestrator(tmp_path)
    await orch.intake(IntentEnvelope(run_id="test-run", objective="test"))
    await orch.route()

    # Create test file
    test_file = tmp_path / "test.txt"
    test_file.write_text("test content")

    # Create a grant with very short TTL
    proposal = CommandProposal(
        run_id="test-run",
        source="model",
        kind="fs.read",
        args={"root": str(tmp_path), "path": "test.txt"},
    )

    # First request - auto-granted (T0)
    result1 = await orch.process_proposal(proposal)
    assert result1["granted"] is True
    assert len(orch.state.active_grants) == 1

    # Manually expire the grant by modifying issued_at
    grant = orch.state.active_grants[0]
    from dataclasses import replace

    expired_grant = replace(grant, issued_at=time.time() - 3600, ttl_seconds=60)
    orch._state = replace(orch.state, active_grants=[expired_grant])

    # Second request with expired grant - should issue new grant
    # The expired grant won't match (filtered by policy engine), so a new one is issued
    result2 = await orch.process_proposal(proposal)
    assert result2["granted"] is True

    # Should have 2 grants now (expired one not removed from state, but new one added)
    # The expired grant stays in state until explicitly revoked
    assert len(orch.state.active_grants) == 2

    # But the new grant should have a more recent issued_at
    grants_by_time = sorted(orch.state.active_grants, key=lambda g: g.issued_at)
    assert grants_by_time[0].issued_at < grants_by_time[1].issued_at


@pytest.mark.asyncio
async def test_grant_lifecycle_multiple_capabilities(tmp_path):
    """Test managing grants for multiple different capabilities."""
    orch = _make_orchestrator(tmp_path)
    await orch.intake(IntentEnvelope(run_id="test-run", objective="test"))
    await orch.route()

    # Create test file
    test_file = tmp_path / "file1.txt"
    test_file.write_text("test")

    # Request multiple low-risk capabilities
    proposals = [
        CommandProposal(
            run_id="test-run",
            source="model",
            kind="fs.read",
            args={"root": str(tmp_path), "path": "file1.txt"},
        ),
        CommandProposal(
            run_id="test-run",
            source="model",
            kind="fs.write.workspace",
            args={"root": str(tmp_path), "path": "file2.txt", "content": "test"},
        ),
        CommandProposal(
            run_id="test-run",
            source="model",
            kind="exec.shell.sandboxed",
            args={"cmd": "echo test", "cwd": str(tmp_path)},
        ),
    ]

    for proposal in proposals:
        result = await orch.process_proposal(proposal)
        assert result["granted"] is True

    # Should have 3 different grants
    assert len(orch.state.active_grants) == 3
    capabilities = {g.capability for g in orch.state.active_grants}
    assert capabilities == {"fs.read", "fs.write.workspace", "exec.shell.sandboxed"}


@pytest.mark.asyncio
async def test_grant_lifecycle_scope_matching(tmp_path):
    """Test that grants are scope-specific."""
    orch = _make_orchestrator(tmp_path)
    await orch.intake(IntentEnvelope(run_id="test-run", objective="test"))
    await orch.route()

    workspace1 = tmp_path / "workspace1"
    workspace2 = tmp_path / "workspace2"
    workspace1.mkdir()
    workspace2.mkdir()

    # Create test files
    (workspace1 / "file.txt").write_text("test1")
    (workspace2 / "file.txt").write_text("test2")

    # Request for workspace1
    proposal1 = CommandProposal(
        run_id="test-run",
        source="model",
        kind="fs.read",
        args={"root": str(workspace1), "path": "file.txt"},
    )

    result1 = await orch.process_proposal(proposal1)
    assert result1["granted"] is True

    # Request for workspace2 - same filename but different root
    # The scope is based on the resource (path), not the root
    # So both will have scope="file.txt" and the grant will be reused
    proposal2 = CommandProposal(
        run_id="test-run",
        source="model",
        kind="fs.read",
        args={"root": str(workspace2), "path": "file.txt"},
    )

    result2 = await orch.process_proposal(proposal2)
    assert result2["granted"] is True

    # The grant is reused because scope is the same (just the path, not root+path)
    # This is the current behavior - grants are scoped by resource path, not full path
    assert len(orch.state.active_grants) == 1
    grant = orch.state.active_grants[0]
    assert grant.scope == "file.txt"


@pytest.mark.asyncio
async def test_grant_lifecycle_dehydration_and_hydration(tmp_path):
    """Test that grants survive dehydration/hydration cycle."""
    orch = _make_orchestrator(tmp_path)
    await orch.intake(IntentEnvelope(run_id="test-run", objective="test"))
    await orch.route()

    # Create test file
    test_file = tmp_path / "test.txt"
    test_file.write_text("test content")

    # Create some grants
    proposal = CommandProposal(
        run_id="test-run",
        source="model",
        kind="fs.read",
        args={"root": str(tmp_path), "path": "test.txt"},
    )

    await orch.process_proposal(proposal)
    assert len(orch.state.active_grants) == 1
    original_grant = orch.state.active_grants[0]

    # Dehydrate
    checkpoint_id = await orch.dehydrate()

    # Create new orchestrator and hydrate
    orch2 = _make_orchestrator(tmp_path)
    state = await orch2.hydrate(checkpoint_id)

    # Grant should be restored
    assert len(state.active_grants) == 1
    restored_grant = state.active_grants[0]
    assert restored_grant.grant_id == original_grant.grant_id
    assert restored_grant.capability == original_grant.capability
