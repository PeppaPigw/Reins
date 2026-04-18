from __future__ import annotations

from pathlib import Path

import pytest

from reins.approval.ledger import ApprovalLedger
from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.event.journal import EventJournal
from reins.kernel.intent.envelope import IntentEnvelope
from reins.kernel.types import Actor, PathKind
from reins.orchestration.orchestrator import AgentHandle, Orchestrator
from reins.policy.engine import PolicyEngine
from reins.policy.rules import PolicyRule


def _make_orchestrator(
    tmp_path: Path,
    *,
    policy_engine: PolicyEngine | None = None,
    approval_ledger: ApprovalLedger | None = None,
) -> tuple[Orchestrator, EventJournal, ApprovalLedger]:
    journal = EventJournal(tmp_path / "journal")
    approvals = approval_ledger or ApprovalLedger(tmp_path / "approvals")
    orchestrator = Orchestrator(
        journal=journal,
        policy_engine=policy_engine or PolicyEngine(),
        approval_ledger=approvals,
    )
    return orchestrator, journal, approvals


async def _load_events(journal: EventJournal, run_id: str) -> list[EventEnvelope]:
    return [event async for event in journal.read_from(run_id)]


@pytest.mark.asyncio
async def test_execute_intent_routes_to_fast_path(tmp_path: Path) -> None:
    orchestrator, journal, _ = _make_orchestrator(tmp_path)
    intent = IntentEnvelope(
        run_id="run-fast",
        objective="read configuration",
        requested_capabilities=["fs.read"],
    )

    result = await orchestrator.execute_intent(intent)

    assert result.path is PathKind.fast
    assert result.status == "completed"
    assert result.subagent_handle is None
    assert result.output["mode"] == "fast"

    events = await _load_events(journal, "run-fast")
    assert [event.type for event in events] == [
        "orchestrator.intent_received",
        "orchestrator.route_decided",
    ]


@pytest.mark.asyncio
async def test_execute_intent_routes_to_deliberative_path(tmp_path: Path) -> None:
    orchestrator, journal, _ = _make_orchestrator(tmp_path)
    intent = IntentEnvelope(
        run_id="run-deliberative",
        objective="push release branch",
        requested_capabilities=["git.push"],
    )

    result = await orchestrator.execute_intent(intent)

    assert result.path is PathKind.deliberative
    assert result.subagent_handle is not None
    assert result.agent_result is not None
    assert result.agent_result.status == "approval_required"
    assert result.error_message == "approval required before deliberative execution"
    assert len(result.approval_requests) == 1

    events = await _load_events(journal, "run-deliberative")
    assert [event.type for event in events] == [
        "orchestrator.intent_received",
        "orchestrator.route_decided",
        "orchestrator.subagent_spawned",
        "orchestrator.subagent_failed",
    ]


@pytest.mark.asyncio
async def test_spawn_subagent_emits_event(tmp_path: Path) -> None:
    orchestrator, journal, _ = _make_orchestrator(tmp_path)

    handle = await orchestrator.spawn_subagent(
        "debug",
        {"run_id": "spawn-run", "task_id": "task-67", "objective": "debug failure"},
    )

    assert handle.agent_type == "debug"
    assert handle.run_id == "spawn-run"
    assert handle.agent_id.startswith("agent-")

    events = await _load_events(journal, "spawn-run")
    assert len(events) == 1
    assert events[0].type == "orchestrator.subagent_spawned"
    assert events[0].payload["agent_id"] == handle.agent_id


@pytest.mark.asyncio
async def test_collect_results_handles_success(tmp_path: Path) -> None:
    orchestrator, journal, _ = _make_orchestrator(tmp_path)
    handle = AgentHandle(
        agent_id="agent-success",
        agent_type="implement",
        run_id="collect-success",
        context={},
    )

    await journal.append(
        EventEnvelope(
            run_id="collect-success",
            actor=Actor.runtime,
            type="orchestrator.subagent_completed",
            payload={
                "agent_id": "agent-success",
                "agent_type": "implement",
                "output": {"summary": "done"},
                "exit_code": 0,
            },
        )
    )

    result = await orchestrator.collect_results(handle)

    assert result.status == "completed"
    assert result.output == {"summary": "done"}
    assert result.exit_code == 0
    assert result.error_message is None


@pytest.mark.asyncio
async def test_collect_results_handles_failure(tmp_path: Path) -> None:
    orchestrator, journal, _ = _make_orchestrator(tmp_path)
    handle = AgentHandle(
        agent_id="agent-failed",
        agent_type="check",
        run_id="collect-failed",
        context={},
    )

    await journal.append(
        EventEnvelope(
            run_id="collect-failed",
            actor=Actor.runtime,
            type="orchestrator.subagent_failed",
            payload={
                "agent_id": "agent-failed",
                "agent_type": "check",
                "status": "failed",
                "output": {},
                "error_message": "tests failed",
                "exit_code": 1,
            },
        )
    )

    result = await orchestrator.collect_results(handle)

    assert result.status == "failed"
    assert result.output == {}
    assert result.exit_code == 1
    assert result.error_message == "tests failed"


@pytest.mark.asyncio
async def test_policy_integration(tmp_path: Path) -> None:
    policy = PolicyEngine(
        rules=[
            PolicyRule(
                name="force-deliberation",
                condition='command.capability == "exec.shell.network"',
                action="require_approval",
                reason="network execution requires deliberation",
            )
        ]
    )
    orchestrator, _, _ = _make_orchestrator(tmp_path, policy_engine=policy)
    intent = IntentEnvelope(
        run_id="policy-run",
        objective="fetch release artifacts",
        requested_capabilities=["exec.shell.network"],
    )

    result = await orchestrator.execute_intent(intent)

    assert len(result.policy_decisions) == 1
    assert result.policy_decisions[0].decision == "ask"
    assert result.policy_decisions[0].matched_rule == "force-deliberation"
    assert result.path is PathKind.deliberative


@pytest.mark.asyncio
async def test_approval_integration(tmp_path: Path) -> None:
    approvals = ApprovalLedger(tmp_path / "approvals")
    orchestrator, _, ledger = _make_orchestrator(tmp_path, approval_ledger=approvals)
    intent = IntentEnvelope(
        run_id="approval-run",
        objective="push release",
        requested_capabilities=["git.push"],
    )

    result = await orchestrator.execute_intent(intent)

    assert len(result.approval_requests) == 1
    request = result.approval_requests[0]
    assert request.run_id == "approval-run"
    assert request.effect.capability == "git.push"
    assert request.reason == "git.push -> push release"
    assert len(ledger.pending) == 1
    assert ledger.pending[0].request_id == request.request_id
