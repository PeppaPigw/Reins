"""Integration test — full vertical slice of the Reins kernel.

Walks the complete lifecycle:
  intent → orchestrator → policy → execute → evaluate →
  subagent → timeline → context compilation

This test exercises every major module in one end-to-end flow.
"""

import pytest
from pathlib import Path

from reins.context.compiler import ContextCompiler
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

    orch = RunOrchestrator(journal, snapshots, checkpoints, policy, context)

    # ---- Phase 1: Intake ----
    intent = IntentEnvelope(run_id="integration-1", objective="refactor auth module")
    state = await orch.intake(intent)
    assert state.status == RunStatus.routing

    # ---- Phase 2: Route ----
    path = await orch.route()
    # With no requested capabilities, routes to fast path
    assert state is not None

    # ---- Phase 3: Execute a safe read command ----
    read_proposal = CommandProposal(
        run_id="integration-1", source="model", kind="fs.read",
        args={"path": "src/auth.py"},
    )

    async def mock_fs_read(kind, args):
        return {"stdout": "class Auth:\n    pass\n", "exit_code": 0}

    result = await orch.process_proposal(read_proposal, execute_fn=mock_fs_read)
    assert result["granted"] is True
    assert result["executed"] is True
    assert "class Auth" in result["observation"]["stdout"]

    # ---- Phase 4: Execute a write command (also T1 → auto-allow) ----
    write_proposal = CommandProposal(
        run_id="integration-1", source="model", kind="fs.write.workspace",
        args={"path": "src/auth.py", "content": "class Auth:\n    pass\n"},
    )

    async def mock_fs_write(kind, args):
        return {"stdout": "", "exit_code": 0, "bytes_written": 24}

    result = await orch.process_proposal(write_proposal, execute_fn=mock_fs_write)
    assert result["granted"] is True

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

    # ---- Phase 6: Spec evaluation ----
    spec_eval = SpecEvaluator()
    eval_result = await spec_eval.evaluate({
        "cwd": str(Path.cwd()),  # checks the real Reins codebase
        "run_id": "integration-1",
    })
    assert eval_result.passed, f"Spec violations: {eval_result.details}"

    # ---- Phase 7: Approval ledger (for a high-risk op) ----
    ledger = ApprovalLedger(tmp_path / "approvals")
    effect = EffectDescriptor(
        capability="git.push", resource="origin/main",
        intent_ref="integration-1", command_id="cmd-push",
    )
    req = await ledger.request("integration-1", effect, "model")
    assert len(ledger.pending) == 1
    grant = await ledger.approve(req.request_id, "human")
    assert grant is not None
    assert len(ledger.pending) == 0

    # ---- Phase 8: Complete the run ----
    final_state = await orch.complete()
    assert final_state.status == RunStatus.completed

    # ---- Phase 9: Timeline reconstruction ----
    tl_builder = TimelineBuilder(journal)
    timeline = await tl_builder.build("integration-1")

    assert timeline.final_status == RunStatus.completed
    assert timeline.event_count >= 6  # started, routed, grants, executions, completion
    assert len(timeline.subagent_ids) == 1

    # Verify timeline has human-readable summaries
    summaries = [e.summary for e in timeline.entries]
    assert any("refactor auth" in s for s in summaries)
    assert any("Spawned subagent" in s for s in summaries)
    assert any("Subagent completed" in s for s in summaries)
    assert any("Run completed" in s for s in summaries)

    # ---- Phase 10: Context compilation ----
    context.load_standing_law(Path.cwd())
    summary = await tl_builder.build_summary("integration-1")
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
