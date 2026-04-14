"""Integration test — full vertical slice of the Reins kernel.

Walks the complete lifecycle:
  intent → orchestrator → policy → execute → evaluate →
  subagent → timeline → context compilation

This test exercises every major module in one end-to-end flow.
"""

import pytest
from pathlib import Path

from reins.context.compiler import ContextCompiler
from reins.execution.dispatcher import ExecutionDispatcher
from reins.evaluation.runner import EvaluationRunner
from reins.evaluation.classifier import FailureClassifier
from reins.evaluation.evaluators.spec import SpecEvaluator
from reins.kernel.event.journal import EventJournal
from reins.kernel.intent.envelope import CommandProposal, IntentEnvelope
from reins.kernel.orchestrator import RunOrchestrator
from reins.kernel.snapshot.store import SnapshotStore
from reins.kernel.types import FailureClass, RunStatus
from reins.memory.checkpoint import CheckpointStore
from reins.policy.approval.ledger import ApprovalLedger, EffectDescriptor
from reins.policy.engine import PolicyEngine
from reins.subagent.manager import SubagentManager, SubagentSpec
from reins.timeline.builder import TimelineBuilder


@pytest.mark.asyncio
async def test_full_vertical_slice(tmp_path):
    """End-to-end: intent → execute → evaluate → subagent → timeline."""

    # ---- Set up kernel infrastructure ----
    journal = EventJournal(tmp_path / "journal.jsonl")
    snapshots = SnapshotStore(tmp_path / "snapshots")
    checkpoints = CheckpointStore(tmp_path / "checkpoints")
    policy = PolicyEngine()
    context = ContextCompiler(token_budget=50_000)
    approvals = ApprovalLedger(tmp_path / "approvals")
    dispatcher = ExecutionDispatcher()
    eval_runner = EvaluationRunner(
        evaluators={"spec": SpecEvaluator()},
    )

    orch = RunOrchestrator(
        journal,
        snapshots,
        checkpoints,
        policy,
        context,
        approvals,
        dispatcher,
        eval_runner,
    )

    # ---- Phase 1: Intake ----
    intent = IntentEnvelope(run_id="integration-1", objective="refactor auth module")
    state = await orch.intake(intent)
    assert state.status == RunStatus.routing

    # ---- Phase 2: Route ----
    await orch.route()
    # With no requested capabilities, routes to fast path
    assert state is not None
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    auth_path = workspace / "src" / "auth.py"
    auth_path.parent.mkdir(parents=True)
    auth_path.write_text("class Auth:\n    pass\n", encoding="utf-8")

    # ---- Phase 3: Execute a safe read command ----
    read_proposal = CommandProposal(
        run_id="integration-1", source="model", kind="fs.read",
        args={"root": str(workspace), "path": "src/auth.py"},
    )

    result = await orch.process_proposal(read_proposal)
    assert result["granted"] is True
    assert result["executed"] is True
    assert "class Auth" in result["observation"]["stdout"]

    # ---- Phase 4: Execute a write command (also T1 → auto-allow) ----
    write_proposal = CommandProposal(
        run_id="integration-1", source="model", kind="fs.write.workspace",
        args={
            "root": str(workspace),
            "path": "src/auth.py",
            "content": "class Auth:\n    pass\n    active = True\n",
        },
    )

    result = await orch.process_proposal(write_proposal)
    assert result["granted"] is True
    assert "active = True" in auth_path.read_text(encoding="utf-8")

    # ---- Phase 5: Local subagent for tests ----
    sub_mgr = SubagentManager(journal, snapshots, checkpoints, policy)
    spec = SubagentSpec(
        objective="write tests for auth module",
        parent_run_id="integration-1",
        max_turns=5,
        token_budget=10_000,
    )
    sub_handle = await sub_mgr.spawn(spec)
    assert sub_mgr.active_count == 1

    # Subagent does a turn
    assert await sub_mgr.report_turn(sub_handle.handle_id) is True

    # Subagent completes
    await sub_mgr.complete(sub_handle.handle_id, {
        "summary": "added 3 tests for Auth class",
        "tests_added": ["test_auth_init", "test_auth_login", "test_auth_logout"],
    })
    assert sub_mgr.active_count == 0

    # ---- Phase 6: Integrated evaluation ----
    status_result = await orch.process_proposal(
        CommandProposal(
            run_id="integration-1",
            source="model",
            kind="git.status",
            args={"repo": str(Path.cwd())},
        ),
        evaluate=True,
        eval_context={"evaluators": ["spec"], "cwd": str(Path.cwd())},
    )
    assert status_result["executed"] is True
    assert status_result["eval_passed"] is True

    # ---- Phase 7: Approval ledger (for a high-risk op) ----
    effect = EffectDescriptor(
        capability="git.push", resource="origin/main",
        intent_ref="integration-1", command_id="cmd-push",
    )
    req = await approvals.request("integration-1", effect, "model")
    assert len(approvals.pending) == 1
    grant = await approvals.approve(req.request_id, "human")
    assert grant is not None
    assert len(approvals.pending) == 0

    # ---- Phase 8: Complete the run ----
    final_state = await orch.complete()
    assert final_state.status == RunStatus.completed

    # ---- Phase 9: Timeline reconstruction ----
    tl_builder = TimelineBuilder(journal)
    timeline = await tl_builder.build("integration-1")

    assert timeline.final_status == RunStatus.completed
    assert timeline.event_count >= 7  # includes integrated eval event
    assert len(timeline.subagent_ids) == 1

    # Verify timeline has human-readable summaries
    summaries = [e.summary for e in timeline.entries]
    assert any("refactor auth" in s for s in summaries)
    assert any("Spawned subagent" in s for s in summaries)
    assert any("Subagent completed" in s for s in summaries)
    assert any("Eval PASS" in s for s in summaries)
    assert any("Run completed" in s for s in summaries)

    # ---- Phase 10: Context compilation ----
    context.load_standing_law(Path.cwd())
    await tl_builder.build_summary("integration-1")
    active_shards = context.build_active_set(
        run_id="integration-1",
        snapshot={"run_phase": "completed"},
        open_nodes=[],
        eval_failures=[],
        affected_files=["src/auth.py"],
    )
    folded = context.add_folded([{
        "episode_id": "ep-1",
        "outcome": "auth module refactored and tested",
        "decisions": ["used handle-based adapter for fs write"],
    }])
    ws = context.compile("integration-1", active_shards, folded)
    assert ws.total_tokens > 0
    assert ws.total_tokens <= ws.budget

    # ---- Phase 11: Failure classification (hypothetical) ----
    classifier = FailureClassifier()
    fc = classifier.classify({"passed": False, "details": "assertion error"}, {})
    assert fc == FailureClass.logic_failure
    route = classifier.repair_route(fc)
    assert route == "change_hypothesis"

    # ---- Verify: reducer replay produces same final state ----
    from reins.kernel.reducer.reducer import reduce
    from reins.kernel.reducer.state import RunState

    replayed_state = RunState(run_id="integration-1")
    async for event in journal.read_from("integration-1"):
        replayed_state = reduce(replayed_state, event)
    assert replayed_state.status == RunStatus.completed
