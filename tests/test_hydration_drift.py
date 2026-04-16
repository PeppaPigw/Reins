"""Tests for hydration drift validation."""

import pytest
import time
from pathlib import Path

from reins.kernel.event.journal import EventJournal
from reins.kernel.reducer.state import RunState, StateSnapshot
from reins.kernel.snapshot.store import SnapshotStore
from reins.kernel.types import GrantRef, RunStatus
from reins.memory.checkpoint import CheckpointManifest, CheckpointStore, DehydrationMachine


@pytest.mark.asyncio
async def test_hydration_filters_expired_grants(tmp_path):
    """Hydration should filter out expired grants."""
    dehydrator = DehydrationMachine()

    # Create snapshot with mixed grants
    valid_grant = GrantRef(
        grant_id="grant-valid",
        capability="fs.read",
        scope="workspace",
        issued_to="model",
        ttl_seconds=600,
        approval_hash=None,
        issued_at=time.time(),
    )

    expired_grant = GrantRef(
        grant_id="grant-expired",
        capability="fs.write.workspace",
        scope="workspace",
        issued_to="model",
        ttl_seconds=60,
        approval_hash=None,
        issued_at=time.time() - 3600,  # 1 hour ago
    )

    snapshot = StateSnapshot(
        run_id="test-run",
        snapshot_id="snap-1",
        event_seq=10,
        reducer_version="0.1.0",
        run_phase="executing",
        active_grants=[valid_grant, expired_grant],
        pending_approvals=[],
        open_questions=[],
    )

    manifest = CheckpointManifest(
        checkpoint_id="ckpt-1",
        run_id="test-run",
        snapshot_id="snap-1",
        event_seq=10,
        worktree_ref=None,
    )

    # Hydrate
    state = await dehydrator.hydrate(manifest, snapshot)

    # Only valid grant should remain
    assert len(state.active_grants) == 1
    assert state.active_grants[0].grant_id == "grant-valid"


@pytest.mark.asyncio
async def test_hydration_keeps_all_valid_grants(tmp_path):
    """Hydration should keep all non-expired grants."""
    dehydrator = DehydrationMachine()

    grant1 = GrantRef(
        grant_id="grant-1",
        capability="fs.read",
        scope="workspace",
        issued_to="model",
        ttl_seconds=600,
        approval_hash=None,
        issued_at=time.time(),
    )

    grant2 = GrantRef(
        grant_id="grant-2",
        capability="exec.shell.sandboxed",
        scope="workspace",
        issued_to="model",
        ttl_seconds=300,
        approval_hash=None,
        issued_at=time.time() - 100,  # 100 seconds ago, still valid
    )

    snapshot = StateSnapshot(
        run_id="test-run",
        snapshot_id="snap-1",
        event_seq=10,
        reducer_version="0.1.0",
        run_phase="executing",
        active_grants=[grant1, grant2],
        pending_approvals=[],
        open_questions=[],
    )

    manifest = CheckpointManifest(
        checkpoint_id="ckpt-1",
        run_id="test-run",
        snapshot_id="snap-1",
        event_seq=10,
        worktree_ref=None,
    )

    state = await dehydrator.hydrate(manifest, snapshot)

    # Both grants should remain
    assert len(state.active_grants) == 2
    grant_ids = {g.grant_id for g in state.active_grants}
    assert grant_ids == {"grant-1", "grant-2"}


@pytest.mark.asyncio
async def test_hydration_with_no_grants(tmp_path):
    """Hydration should work when there are no grants."""
    dehydrator = DehydrationMachine()

    snapshot = StateSnapshot(
        run_id="test-run",
        snapshot_id="snap-1",
        event_seq=10,
        reducer_version="0.1.0",
        run_phase="executing",
        active_grants=[],
        pending_approvals=[],
        open_questions=[],
    )

    manifest = CheckpointManifest(
        checkpoint_id="ckpt-1",
        run_id="test-run",
        snapshot_id="snap-1",
        event_seq=10,
        worktree_ref=None,
    )

    state = await dehydrator.hydrate(manifest, snapshot)

    assert len(state.active_grants) == 0


@pytest.mark.asyncio
async def test_hydration_with_all_expired_grants(tmp_path):
    """Hydration should handle case where all grants are expired."""
    dehydrator = DehydrationMachine()

    expired1 = GrantRef(
        grant_id="grant-1",
        capability="fs.read",
        scope="workspace",
        issued_to="model",
        ttl_seconds=60,
        approval_hash=None,
        issued_at=time.time() - 3600,
    )

    expired2 = GrantRef(
        grant_id="grant-2",
        capability="fs.write.workspace",
        scope="workspace",
        issued_to="model",
        ttl_seconds=120,
        approval_hash=None,
        issued_at=time.time() - 7200,
    )

    snapshot = StateSnapshot(
        run_id="test-run",
        snapshot_id="snap-1",
        event_seq=10,
        reducer_version="0.1.0",
        run_phase="executing",
        active_grants=[expired1, expired2],
        pending_approvals=[],
        open_questions=[],
    )

    manifest = CheckpointManifest(
        checkpoint_id="ckpt-1",
        run_id="test-run",
        snapshot_id="snap-1",
        event_seq=10,
        worktree_ref=None,
    )

    state = await dehydrator.hydrate(manifest, snapshot)

    # All grants expired, should be empty
    assert len(state.active_grants) == 0


@pytest.mark.asyncio
async def test_hydration_preserves_other_state(tmp_path):
    """Hydration should preserve other state fields while filtering grants."""
    dehydrator = DehydrationMachine()

    valid_grant = GrantRef(
        grant_id="grant-valid",
        capability="fs.read",
        scope="workspace",
        issued_to="model",
        ttl_seconds=600,
        approval_hash=None,
        issued_at=time.time(),
    )

    expired_grant = GrantRef(
        grant_id="grant-expired",
        capability="fs.write.workspace",
        scope="workspace",
        issued_to="model",
        ttl_seconds=60,
        approval_hash=None,
        issued_at=time.time() - 3600,
    )

    snapshot = StateSnapshot(
        run_id="test-run",
        snapshot_id="snap-1",
        event_seq=10,
        reducer_version="0.1.0",
        run_phase="executing",
        active_grants=[valid_grant, expired_grant],
        pending_approvals=["approval-1", "approval-2"],
        open_questions=["question-1"],
        current_node_id="node-5",
    )

    manifest = CheckpointManifest(
        checkpoint_id="ckpt-1",
        run_id="test-run",
        snapshot_id="snap-1",
        event_seq=10,
        worktree_ref="worktree-ref-1",
        resume_plan_ref="worktree-ref-1",
    )

    state = await dehydrator.hydrate(manifest, snapshot)

    # Grants filtered
    assert len(state.active_grants) == 1
    assert state.active_grants[0].grant_id == "grant-valid"

    # Other state preserved
    assert state.pending_approvals == ["approval-1", "approval-2"]
    assert state.open_questions == ["question-1"]
    assert state.current_node_id == "node-5"
    # working_set_manifest_ref comes from manifest.resume_plan_ref when snapshot doesn't have it
    assert state.working_set_manifest_ref == "worktree-ref-1"
    assert state.status == RunStatus.resumable
