"""Tests for API server multi-process and restart scenarios."""

import pytest
from pathlib import Path

from reins.api.registry import RunRegistry
from reins.kernel.types import RunStatus


@pytest.mark.asyncio
async def test_multiple_registries_share_state_via_journal(tmp_path):
    """Multiple registry instances should share state through journal."""
    # Registry 1 creates a run
    registry1 = RunRegistry(tmp_path)
    state1 = await registry1.create_run(objective="shared run")
    run_id = state1.run_id

    # Registry 2 (simulating different process) can read the state
    registry2 = RunRegistry(tmp_path)
    state2 = await registry2.get_state(run_id)

    assert state2 is not None
    assert state2.run_id == run_id
    assert state2.status == state1.status


@pytest.mark.asyncio
async def test_concurrent_runs_isolated(tmp_path):
    """Concurrent runs should be isolated in separate journal files."""
    registry = RunRegistry(tmp_path)

    # Create multiple runs
    state1 = await registry.create_run(objective="run 1")
    state2 = await registry.create_run(objective="run 2")
    state3 = await registry.create_run(objective="run 3")

    # Each should have separate journal files
    journal_dir = tmp_path / "journals"
    assert (journal_dir / f"{state1.run_id}.jsonl").exists()
    assert (journal_dir / f"{state2.run_id}.jsonl").exists()
    assert (journal_dir / f"{state3.run_id}.jsonl").exists()

    # States should be independent
    assert state1.run_id != state2.run_id
    assert state2.run_id != state3.run_id


@pytest.mark.asyncio
async def test_registry_restart_preserves_all_runs(tmp_path):
    """After restart, registry should be able to access all previous runs."""
    registry1 = RunRegistry(tmp_path)

    # Create multiple runs
    run_ids = []
    for i in range(5):
        state = await registry1.create_run(objective=f"run {i}")
        run_ids.append(state.run_id)

    # Simulate restart
    registry2 = RunRegistry(tmp_path)

    # All runs should be accessible
    for run_id in run_ids:
        state = await registry2.get_state(run_id)
        assert state is not None
        assert state.run_id == run_id


@pytest.mark.asyncio
async def test_registry_handles_partial_state(tmp_path):
    """Registry should handle runs that were interrupted mid-execution."""
    registry1 = RunRegistry(tmp_path)

    # Create run and route it
    state1 = await registry1.create_run(objective="interrupted run")
    run_id = state1.run_id

    orch = registry1._orchestrators[run_id]
    await orch.route()

    # Simulate crash (don't clean up)
    del registry1

    # New registry should rebuild state correctly
    registry2 = RunRegistry(tmp_path)
    state2 = await registry2.get_state(run_id)

    assert state2 is not None
    assert state2.run_id == run_id
    # State should reflect the routing that happened
    assert state2.status in [RunStatus.executing, RunStatus.planning]


@pytest.mark.asyncio
async def test_registry_concurrent_access_same_run(tmp_path):
    """Multiple registries accessing same run should see consistent state."""
    registry1 = RunRegistry(tmp_path)
    registry2 = RunRegistry(tmp_path)

    # Registry 1 creates run
    state1 = await registry1.create_run(objective="concurrent access")
    run_id = state1.run_id

    # Registry 2 reads it
    state2 = await registry2.get_state(run_id)
    assert state2 is not None
    assert state2.run_id == run_id

    # Both should see same status
    assert state1.status == state2.status


@pytest.mark.asyncio
async def test_registry_submit_command_after_rebuild(tmp_path):
    """Commands should work on rebuilt orchestrators."""
    registry1 = RunRegistry(tmp_path)

    # Create workspace and test file
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    test_file = workspace / "test.txt"
    test_file.write_text("test content")

    # Create and route run
    state1 = await registry1.create_run(objective="test commands")
    run_id = state1.run_id
    orch = registry1._orchestrators[run_id]
    await orch.route()

    # Simulate restart
    registry2 = RunRegistry(tmp_path)

    # Rebuild state
    state2 = await registry2.get_state(run_id)
    assert state2 is not None

    # Submit command should work
    result = await registry2.submit_command(
        run_id=run_id,
        kind="fs.read",
        args={"root": str(workspace), "path": "test.txt"},
    )

    # Should get policy decision and execution
    assert "granted" in result
    assert result["granted"] is True
    assert "test content" in result["observation"]["stdout"]


@pytest.mark.asyncio
async def test_registry_handles_corrupted_journal_gracefully(tmp_path):
    """Registry should handle missing/corrupted journal files gracefully."""
    registry = RunRegistry(tmp_path)

    # Try to get state for nonexistent run
    state = await registry.get_state("nonexistent-run-id")
    assert state is None

    # Create run
    state1 = await registry.create_run(objective="test")
    run_id = state1.run_id

    # Delete journal file
    journal_file = tmp_path / "journals" / f"{run_id}.jsonl"
    journal_file.unlink()

    # New registry should return None for deleted journal
    registry2 = RunRegistry(tmp_path)
    state2 = await registry2.get_state(run_id)
    assert state2 is None


@pytest.mark.asyncio
async def test_registry_timeline_works_after_restart(tmp_path):
    """Timeline should be accessible after registry restart."""
    registry1 = RunRegistry(tmp_path)

    # Create run
    state1 = await registry1.create_run(objective="timeline test")
    run_id = state1.run_id

    # Simulate restart
    registry2 = RunRegistry(tmp_path)

    # Timeline should be accessible
    timeline = await registry2.get_timeline(run_id)
    assert timeline is not None
    assert "run_id" in timeline
    assert timeline["run_id"] == run_id
