"""Tests for the local subagent manager."""

import pytest

from reins.kernel.event.builder import EventBuilder
from reins.kernel.event.journal import EventJournal
from reins.kernel.reducer.reducer import reduce
from reins.kernel.reducer.state import RunState
from reins.kernel.snapshot.store import SnapshotStore
from reins.kernel.types import GrantRef
from reins.memory.checkpoint import CheckpointStore
from reins.policy.engine import PolicyEngine
from reins.subagent.manager import SubagentManager, SubagentSpec, SubagentStatus


def _make_manager(tmp_path):
    return SubagentManager(
        journal=EventJournal(tmp_path / "journal.jsonl"),
        snapshot_store=SnapshotStore(tmp_path / "snapshots"),
        checkpoint_store=CheckpointStore(tmp_path / "checkpoints"),
        policy_engine=PolicyEngine(),
    )


@pytest.mark.asyncio
async def test_spawn_creates_handle(tmp_path):
    mgr = _make_manager(tmp_path)
    spec = SubagentSpec(
        objective="write unit tests",
        parent_run_id="parent-1",
        max_turns=10,
    )
    handle = await mgr.spawn(spec)
    assert handle.status == SubagentStatus.running
    assert handle.parent_run_id == "parent-1"
    assert handle.child_run_id  # non-empty ULID
    assert mgr.active_count == 1


@pytest.mark.asyncio
async def test_complete_subagent(tmp_path):
    mgr = _make_manager(tmp_path)
    spec = SubagentSpec(objective="fix lint", parent_run_id="parent-2")
    handle = await mgr.spawn(spec)

    completed = await mgr.complete(handle.handle_id, {"summary": "fixed 3 lint errors"})
    assert completed is not None
    assert completed.status == SubagentStatus.completed
    assert completed.result["summary"] == "fixed 3 lint errors"
    assert mgr.active_count == 0
    assert len(mgr.history) == 1


@pytest.mark.asyncio
async def test_fail_subagent(tmp_path):
    mgr = _make_manager(tmp_path)
    spec = SubagentSpec(objective="deploy", parent_run_id="parent-3")
    handle = await mgr.spawn(spec)

    failed = await mgr.fail(handle.handle_id, "deployment target unreachable")
    assert failed is not None
    assert failed.status == SubagentStatus.failed
    assert "unreachable" in failed.result["error"]
    assert mgr.active_count == 0


@pytest.mark.asyncio
async def test_turn_limit_enforced(tmp_path):
    mgr = _make_manager(tmp_path)
    spec = SubagentSpec(objective="loop task", parent_run_id="parent-4", max_turns=3)
    handle = await mgr.spawn(spec)

    assert await mgr.report_turn(handle.handle_id) is True   # turn 1
    assert await mgr.report_turn(handle.handle_id) is True   # turn 2
    assert await mgr.report_turn(handle.handle_id) is False  # turn 3 → abort
    assert mgr.active_count == 0
    assert mgr.history[-1].status == SubagentStatus.aborted


@pytest.mark.asyncio
async def test_abort_subagent(tmp_path):
    mgr = _make_manager(tmp_path)
    spec = SubagentSpec(objective="long task", parent_run_id="parent-5")
    handle = await mgr.spawn(spec)

    await mgr.abort(handle.handle_id, "user cancelled")
    assert mgr.active_count == 0
    assert mgr.history[-1].status == SubagentStatus.aborted


@pytest.mark.asyncio
async def test_spawn_emits_correlation_event(tmp_path):
    """Spawning a subagent should emit a correlated event on the parent journal."""
    journal = EventJournal(tmp_path / "journal.jsonl")
    mgr = SubagentManager(
        journal, SnapshotStore(tmp_path / "s"),
        CheckpointStore(tmp_path / "c"), PolicyEngine(),
    )
    spec = SubagentSpec(objective="test correlation", parent_run_id="parent-6")
    handle = await mgr.spawn(spec)

    events = []
    async for e in journal.read_from("parent-6"):
        events.append(e)

    # Should have subagent.spawned event on the parent run
    spawn_events = [e for e in events if e.type == "subagent.spawned"]
    assert len(spawn_events) == 1
    assert spawn_events[0].correlation_id == handle.child_run_id


@pytest.mark.asyncio
async def test_inherited_grants_recorded(tmp_path):
    mgr = _make_manager(tmp_path)
    await EventBuilder(mgr._journal).emit_grant_issued(
        "parent-7",
        "g1",
        "fs.read",
        "workspace",
        "parent",
        600,
    )

    # Rebuild parent state to get the actual grant with correct issued_at
    parent_state = RunState(run_id="parent-7")
    async for event in mgr._journal.read_from("parent-7"):
        parent_state = reduce(parent_state, event)

    grant = parent_state.active_grants[0]

    spec = SubagentSpec(
        objective="read files",
        parent_run_id="parent-7",
        inherited_grants=[grant],
    )
    handle = await mgr.spawn(spec)

    # Verify the spawn event payload contains inherited grants
    journal = mgr._journal
    events = []
    async for e in journal.read_from("parent-7"):
        events.append(e)
    spawn_events = [e for e in events if e.type == "subagent.spawned"]
    assert "g1" in spawn_events[0].payload["inherited_grants"]

    child_orch = mgr.get_orchestrator(handle.handle_id)
    assert child_orch is not None
    assert child_orch.state is not None
    assert any(item.grant_id == "g1" for item in child_orch.state.active_grants)


@pytest.mark.asyncio
async def test_forged_inherited_grants_are_rejected(tmp_path):
    mgr = _make_manager(tmp_path)
    forged = GrantRef(
        grant_id="forged",
        capability="deploy.prod",
        scope="production",
        issued_to="parent",
        ttl_seconds=3600,
        approval_hash="fake",
        issued_at=1234567890.0,
    )

    with pytest.raises(ValueError, match="inherited grants must be an active subset"):
        await mgr.spawn(
            SubagentSpec(
                objective="deploy",
                parent_run_id="parent-8",
                inherited_grants=[forged],
            ),
        )
