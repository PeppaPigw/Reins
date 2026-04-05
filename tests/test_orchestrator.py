"""Tests for the run orchestrator — the supervisor loop."""

import asyncio
from pathlib import Path

import pytest

from reins.context.compiler import ContextCompiler
from reins.kernel.event.journal import EventJournal
from reins.kernel.intent.envelope import CommandProposal, IntentEnvelope
from reins.kernel.orchestrator import RunOrchestrator
from reins.kernel.snapshot.store import SnapshotStore
from reins.kernel.types import FailureClass, RunStatus
from reins.memory.checkpoint import CheckpointStore
from reins.policy.engine import PolicyEngine


def _make_orchestrator(tmp_path: Path) -> RunOrchestrator:
    journal = EventJournal(tmp_path / "journal.jsonl")
    snapshots = SnapshotStore(tmp_path / "snapshots")
    checkpoints = CheckpointStore(tmp_path / "checkpoints")
    policy = PolicyEngine()
    context = ContextCompiler()
    return RunOrchestrator(journal, snapshots, checkpoints, policy, context)


@pytest.mark.asyncio
async def test_full_lifecycle(tmp_path):
    """Test intake → route → execute → complete lifecycle."""
    orch = _make_orchestrator(tmp_path)

    # Intake
    intent = IntentEnvelope(run_id="run-1", objective="fix the bug")
    state = await orch.intake(intent)
    assert state.status == RunStatus.routing

    # Route
    path = await orch.route()
    assert path is not None
    assert orch.state is not None

    # Process a safe command (fs.read is T0 → auto-allow)
    proposal = CommandProposal(
        run_id="run-1", source="model", kind="fs.read",
        args={"path": "src/foo.py"},
    )
    result = await orch.process_proposal(proposal)
    assert result["granted"] is True
    assert result["executed"] is True

    # Complete
    final = await orch.complete()
    assert final.status == RunStatus.completed


@pytest.mark.asyncio
async def test_policy_deny(tmp_path):
    """A T4 capability should be denied."""
    orch = _make_orchestrator(tmp_path)
    await orch.intake(IntentEnvelope(run_id="run-2", objective="deploy"))
    await orch.route()

    proposal = CommandProposal(
        run_id="run-2", source="model", kind="deploy.prod",
        args={"target": "production"},
    )
    result = await orch.process_proposal(proposal)
    assert result["granted"] is False
    assert "risk tier" in result["reason"].lower() or "deny" in result.get("reason", "").lower()


@pytest.mark.asyncio
async def test_policy_ask_approval(tmp_path):
    """A T2-T3 capability should trigger an approval request."""
    orch = _make_orchestrator(tmp_path)
    await orch.intake(IntentEnvelope(run_id="run-3", objective="push code"))
    await orch.route()

    proposal = CommandProposal(
        run_id="run-3", source="model", kind="git.push",
        args={"branch": "main"},
    )
    result = await orch.process_proposal(proposal)
    assert result["granted"] is False
    assert result["needs_approval"] is True
    assert orch.state is not None
    assert orch.state.status == RunStatus.waiting_approval


@pytest.mark.asyncio
async def test_dehydrate_and_status(tmp_path):
    """Test dehydration sets the run to dehydrated status."""
    orch = _make_orchestrator(tmp_path)
    await orch.intake(IntentEnvelope(run_id="run-4", objective="long task"))
    await orch.route()

    checkpoint_id = await orch.dehydrate()
    assert checkpoint_id
    assert orch.state is not None
    assert orch.state.status == RunStatus.dehydrated


@pytest.mark.asyncio
async def test_fail_with_class(tmp_path):
    """Test failing a run with a typed failure class."""
    orch = _make_orchestrator(tmp_path)
    await orch.intake(IntentEnvelope(run_id="run-5", objective="test"))
    await orch.route()

    state = await orch.fail(FailureClass.environment_failure, "missing executable")
    assert state.status == RunStatus.failed
    assert state.last_failure_class == FailureClass.environment_failure


@pytest.mark.asyncio
async def test_abort_is_terminal(tmp_path):
    """Test human-initiated abort."""
    orch = _make_orchestrator(tmp_path)
    await orch.intake(IntentEnvelope(run_id="run-6", objective="test"))
    await orch.route()

    state = await orch.abort("user cancelled")
    assert state.status == RunStatus.aborted


@pytest.mark.asyncio
async def test_execute_fn_called(tmp_path):
    """When an execute_fn is provided, it should be called."""
    orch = _make_orchestrator(tmp_path)
    await orch.intake(IntentEnvelope(run_id="run-7", objective="test"))
    await orch.route()

    calls = []

    async def mock_execute(kind, args):
        calls.append((kind, args))
        return {"stdout": "hello", "exit_code": 0}

    proposal = CommandProposal(
        run_id="run-7", source="model", kind="fs.read",
        args={"path": "/tmp/x"},
    )
    result = await orch.process_proposal(proposal, execute_fn=mock_execute)
    assert result["granted"] is True
    assert len(calls) == 1
    assert calls[0][0] == "fs.read"
    assert result["observation"]["stdout"] == "hello"
