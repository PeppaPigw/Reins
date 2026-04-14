"""Tests for the run orchestrator — the supervisor loop."""

from pathlib import Path

import pytest
from datetime import UTC, datetime

from reins.context.compiler import ContextCompiler
from reins.execution.dispatcher import ExecutionDispatcher
from reins.evaluation.evaluators.base import EvalResult, Evaluator
from reins.evaluation.runner import EvaluationRunner
from reins.kernel.event.journal import EventJournal
from reins.kernel.intent.envelope import CommandProposal, IntentEnvelope
from reins.kernel.orchestrator import RunOrchestrator
from reins.kernel.reducer.state import CompletedRepair
from reins.kernel.snapshot.store import SnapshotStore
from reins.kernel.types import FailureClass, RunStatus
from reins.memory.checkpoint import CheckpointStore
from reins.policy.approval.ledger import ApprovalLedger
from reins.policy.engine import PolicyEngine


class StaticEvaluator(Evaluator):
    def __init__(self, result: EvalResult) -> None:
        self._result = result

    async def evaluate(self, context: dict) -> EvalResult:
        return EvalResult(
            run_id=context["run_id"],
            command_id=context["command_id"],
            evaluator_kind=self._result.evaluator_kind,
            passed=self._result.passed,
            score=self._result.score,
            details=self._result.details,
            failure_class=self._result.failure_class,
            repair_hints=list(self._result.repair_hints),
            eval_id=self._result.eval_id,
            ts=self._result.ts,
        )


def _make_orchestrator(
    tmp_path: Path,
    evaluation_runner: EvaluationRunner | None = None,
) -> RunOrchestrator:
    journal = EventJournal(tmp_path / "journal.jsonl")
    snapshots = SnapshotStore(tmp_path / "snapshots")
    checkpoints = CheckpointStore(tmp_path / "checkpoints")
    policy = PolicyEngine()
    context = ContextCompiler()
    approvals = ApprovalLedger(tmp_path / "approvals")
    dispatcher = ExecutionDispatcher()
    return RunOrchestrator(
        journal,
        snapshots,
        checkpoints,
        policy,
        context,
        approvals,
        dispatcher,
        evaluation_runner,
    )


@pytest.mark.asyncio
async def test_full_lifecycle(tmp_path):
    """Test intake → route → execute → complete lifecycle."""
    orch = _make_orchestrator(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "src" / "foo.py"
    target.parent.mkdir(parents=True)
    target.write_text("print('hello')\n", encoding="utf-8")

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
        args={"root": str(workspace), "path": "src/foo.py"},
    )
    result = await orch.process_proposal(proposal)
    assert result["granted"] is True
    assert result["executed"] is True
    assert result["command_id"] != proposal.proposal_id

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
    assert result["request_id"]
    assert orch.state is not None
    assert orch.state.status == RunStatus.waiting_approval


@pytest.mark.asyncio
async def test_process_proposal_materializes_command_envelope_before_execution(tmp_path):
    """Trusted commands get their own command id before dispatch."""
    orch = _make_orchestrator(tmp_path)
    await orch.intake(IntentEnvelope(run_id="run-envelope", objective="read file"))
    await orch.route()

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "demo.txt"
    target.write_text("envelope\n", encoding="utf-8")

    proposal = CommandProposal(
        run_id="run-envelope",
        source="model",
        kind="fs.read",
        args={"root": str(workspace), "path": "demo.txt"},
    )
    result = await orch.process_proposal(proposal)

    assert result["granted"] is True
    assert result["command_id"] != proposal.proposal_id
    assert orch.state is not None
    assert len(orch.state.open_handles) == 1

    journal = EventJournal(tmp_path / "journal.jsonl")
    events = [event async for event in journal.read_from("run-envelope")]
    executed = [event for event in events if event.type == "command.executed"]
    assert len(executed) == 1
    assert executed[0].payload["command_id"] == result["command_id"]
    assert executed[0].payload["command_id"] != proposal.proposal_id


@pytest.mark.asyncio
async def test_static_validation_blocks_invalid_command_before_dispatch(tmp_path):
    """Invalid command args are rejected before policy or execution."""
    orch = _make_orchestrator(tmp_path)
    await orch.intake(IntentEnvelope(run_id="run-invalid", objective="read file"))
    await orch.route()

    result = await orch.process_proposal(
        CommandProposal(
            run_id="run-invalid",
            source="model",
            kind="fs.read",
            args={},
        )
    )

    assert result["granted"] is False
    assert "missing required args" in result["reason"]
    assert orch.state is not None
    assert orch.state.pending_approvals == []
    assert orch.state.open_handles == []

    journal = EventJournal(tmp_path / "journal.jsonl")
    events = [event async for event in journal.read_from("run-invalid")]
    assert all(event.type != "command.executed" for event in events)


@pytest.mark.asyncio
async def test_failing_evaluation_returns_repair_route_and_emits_event(tmp_path):
    """Integrated evaluation should return typed repair routing."""
    runner = EvaluationRunner(
        evaluators={
            "static-fail": StaticEvaluator(
                EvalResult(
                    run_id="ignored",
                    command_id=None,
                    evaluator_kind="static-fail",
                    passed=False,
                    score=0.0,
                    details="assertion error",
                    failure_class=None,
                    repair_hints=["fix assertion"],
                    eval_id="eval-static-fail",
                    ts=datetime.now(UTC),
                )
            )
        }
    )
    orch = _make_orchestrator(tmp_path, evaluation_runner=runner)
    await orch.intake(IntentEnvelope(run_id="run-eval", objective="write file"))
    await orch.route()

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = await orch.process_proposal(
        CommandProposal(
            run_id="run-eval",
            source="model",
            kind="fs.write.workspace",
            args={"root": str(workspace), "path": "demo.txt", "content": "x"},
        ),
        evaluate=True,
        eval_context={
            "evaluators": ["static-fail"],
            "prior_hypotheses": ["same hypothesis"],
        },
    )

    assert result["executed"] is True
    assert result["eval_passed"] is False
    assert result["failure_class"] == FailureClass.logic_failure.value
    assert result["repair_route"] == "change_hypothesis"
    assert result["retry_allowed"] is False
    assert orch.state is not None
    assert orch.state.last_failure_class == FailureClass.logic_failure

    journal = EventJournal(tmp_path / "journal.jsonl")
    events = [event async for event in journal.read_from("run-eval")]
    assert any(event.type == "eval.completed" for event in events)


@pytest.mark.asyncio
async def test_repair_attempt_clears_pending_repair_for_mutating_command(tmp_path):
    """A new T1 repair attempt should supersede stale pending repair state."""
    orch = _make_orchestrator(tmp_path)
    await orch.intake(IntentEnvelope(run_id="run-repair", objective="repair failure"))
    await orch.route()

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    await orch.fail(FailureClass.logic_failure, "initial failure")
    repair_event = await orch._builder.emit_repair_required(  # noqa: SLF001
        "run-repair",
        "eval-1",
        "logic_failure",
        "change_hypothesis",
        False,
        "assertion error",
        ["fix assertion"],
        command_id="cmd-old",
    )
    orch.apply_event(repair_event)

    result = await orch.process_proposal(
        CommandProposal(
            run_id="run-repair",
            source="model",
            kind="fs.write.workspace",
            args={"root": str(workspace), "path": "demo.txt", "content": "fixed"},
        ),
    )

    assert result["executed"] is True
    assert orch.state is not None
    assert orch.state.pending_repair is None
    assert orch.state.repairing_command_id == result["command_id"]


@pytest.mark.asyncio
async def test_successful_repair_attempt_emits_repair_finished(tmp_path):
    """A passing evaluated repair attempt should emit repair.finished and clear repair state."""
    runner = EvaluationRunner(
        evaluators={
            "static-pass": StaticEvaluator(
                EvalResult(
                    run_id="ignored",
                    command_id=None,
                    evaluator_kind="static-pass",
                    passed=True,
                    score=1.0,
                    details="all good",
                    failure_class=None,
                    repair_hints=[],
                    eval_id="eval-static-pass",
                    ts=datetime.now(UTC),
                )
            )
        }
    )
    orch = _make_orchestrator(tmp_path, evaluation_runner=runner)
    await orch.intake(IntentEnvelope(run_id="run-repair-finish", objective="repair failure"))
    await orch.route()

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    repair_event = await orch._builder.emit_repair_required(  # noqa: SLF001
        "run-repair-finish",
        "eval-1",
        "logic_failure",
        "change_hypothesis",
        False,
        "assertion error",
        ["fix assertion"],
        command_id="cmd-old",
    )
    orch.apply_event(repair_event)

    result = await orch.process_proposal(
        CommandProposal(
            run_id="run-repair-finish",
            source="model",
            kind="fs.write.workspace",
            args={"root": str(workspace), "path": "demo.txt", "content": "fixed"},
        ),
        evaluate=True,
        eval_context={"evaluators": ["static-pass"]},
    )

    assert result["executed"] is True
    assert result["eval_passed"] is True
    assert orch.state is not None
    assert orch.state.last_failure_class is None
    assert orch.state.pending_repair is None
    assert orch.state.repairing_command_id is None
    assert orch.state.last_completed_repair == CompletedRepair(
        eval_id="eval-static-pass",
        command_id=result["command_id"],
        failure_class=FailureClass.logic_failure,
    )

    journal = EventJournal(tmp_path / "journal.jsonl")
    events = [event async for event in journal.read_from("run-repair-finish")]
    assert any(event.type == "repair.started" for event in events)
    assert any(event.type == "repair.finished" for event in events)

    checkpoint_id = await orch.dehydrate()
    restored = _make_orchestrator(tmp_path, evaluation_runner=runner)
    resumed = await restored.hydrate(checkpoint_id)
    assert resumed.last_completed_repair == CompletedRepair(
        eval_id="eval-static-pass",
        command_id=result["command_id"],
        failure_class=FailureClass.logic_failure,
    )


@pytest.mark.asyncio
async def test_repair_attempt_not_started_for_read_only_command(tmp_path):
    """Read-only inspection should not clear pending repair state."""
    orch = _make_orchestrator(tmp_path)
    await orch.intake(IntentEnvelope(run_id="run-read-after-fail", objective="inspect"))
    await orch.route()

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "demo.txt").write_text("x", encoding="utf-8")

    repair_event = await orch._builder.emit_repair_required(  # noqa: SLF001
        "run-read-after-fail",
        "eval-1",
        "logic_failure",
        "change_hypothesis",
        False,
        "assertion error",
        ["fix assertion"],
        command_id="cmd-old",
    )
    orch.apply_event(repair_event)

    result = await orch.process_proposal(
        CommandProposal(
            run_id="run-read-after-fail",
            source="model",
            kind="fs.read",
            args={"root": str(workspace), "path": "demo.txt"},
        ),
    )

    assert result["executed"] is True
    assert orch.state is not None
    assert orch.state.pending_repair is not None
    assert orch.state.repairing_command_id is None


@pytest.mark.asyncio
async def test_route_uses_intent_capabilities(tmp_path):
    """Deliberative capabilities on the intent should route out of fast path."""
    orch = _make_orchestrator(tmp_path)
    await orch.intake(IntentEnvelope(
        run_id="run-route",
        objective="push code",
        requested_capabilities=["git.push"],
    ))

    path = await orch.route()
    assert path.value == "deliberative"


@pytest.mark.asyncio
async def test_route_remote_does_not_execute_locally(tmp_path):
    """A2A commands must not fall through to local execution."""
    orch = _make_orchestrator(tmp_path)
    await orch.intake(IntentEnvelope(run_id="run-remote", objective="call remote agent"))
    await orch.route()

    result = await orch.process_proposal(
        CommandProposal(
            run_id="run-remote",
            source="model",
            kind="a2a.agent.call",
            args={"agent": "planner"},
        ),
    )
    assert result["granted"] is False
    assert result["routed_remote"] is True
    assert orch.state is not None
    assert orch.state.status == RunStatus.waiting_external


@pytest.mark.asyncio
async def test_approval_resolution_issues_grant(tmp_path):
    """Approving a request should clear pending state and allow exact retry."""
    orch = _make_orchestrator(tmp_path)
    await orch.intake(IntentEnvelope(run_id="run-approve", objective="write to network"))
    await orch.route()

    # Request approval for exec.shell.network (T2 capability)
    result = await orch.process_proposal(
        CommandProposal(
            run_id="run-approve",
            source="model",
            kind="exec.shell.network",
            args={"cmd": "curl https://example.com", "cwd": str(tmp_path)},
        ),
    )
    assert result["needs_approval"] is True

    grant = await orch.approve(result["request_id"])

    # Retry with approval granted
    retried = await orch.process_proposal(
        CommandProposal(
            run_id="run-approve",
            source="model",
            kind="exec.shell.network",
            args={"cmd": "curl https://example.com", "cwd": str(tmp_path)},
        ),
    )

    assert grant is not None
    assert orch.state is not None
    assert orch.state.pending_approvals == []
    assert any(item.capability == "exec.shell.network" for item in orch.state.active_grants)
    assert retried["granted"] is True
    assert retried["executed"] is True


@pytest.mark.asyncio
async def test_dehydrate_and_status(tmp_path):
    """Test dehydration persists enough state to hydrate back into a fresh run."""
    orch = _make_orchestrator(tmp_path)
    await orch.intake(IntentEnvelope(run_id="run-4", objective="long task"))
    await orch.route()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "src" / "foo.py"
    target.parent.mkdir(parents=True)
    target.write_text("print('hello')\n", encoding="utf-8")
    await orch.process_proposal(
        CommandProposal(
            run_id="run-4",
            source="model",
            kind="fs.read",
            args={"root": str(workspace), "path": "src/foo.py"},
        ),
    )

    checkpoint_id = await orch.dehydrate()
    assert checkpoint_id
    assert orch.state is not None
    assert orch.state.status == RunStatus.dehydrated
    assert orch.state.snapshot_id is not None

    restored = _make_orchestrator(tmp_path)
    resumed = await restored.hydrate(checkpoint_id)
    assert resumed.status == RunStatus.resumable
    assert resumed.last_checkpoint_id == checkpoint_id
    assert any(item.capability == "fs.read" for item in resumed.active_grants)
    assert any(handle.adapter_kind == "fs" for handle in resumed.open_handles)


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
async def test_unsupported_capability_rejected(tmp_path):
    """Unsupported capabilities should be rejected, not dry-run."""
    orch = _make_orchestrator(tmp_path)
    await orch.intake(IntentEnvelope(run_id="run-7", objective="test"))
    await orch.route()

    # Use a capability that's not in CAPABILITY_RISK_TIERS at all
    proposal = CommandProposal(
        run_id="run-7", source="model", kind="email.send",
        args={"to": "test@example.com", "subject": "test"},
    )
    result = await orch.process_proposal(proposal)
    assert result["granted"] is False
    assert "unknown capability" in result["reason"]

    # Verify no command.executed event was emitted
    journal = EventJournal(tmp_path / "journal.jsonl")
    events = [event async for event in journal.read_from("run-7")]
    assert all(event.type != "command.executed" for event in events)
