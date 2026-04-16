"""Tests for RunRegistry cold start and state rebuilding."""

import pytest
from pathlib import Path

from reins.api.registry import RunRegistry
from reins.kernel.types import RunStatus


@pytest.mark.asyncio
async def test_registry_cold_start_rebuild(tmp_path):
    """Registry should rebuild state from journal after restart."""
    registry = RunRegistry(tmp_path)

    # Create a run and execute some operations
    state1 = await registry.create_run(
        objective="test cold start",
        issuer="user",
        constraints=["test constraint"],
    )
    run_id = state1.run_id

    # Verify initial state
    assert state1.status == RunStatus.routing

    # Simulate process restart by creating new registry
    registry2 = RunRegistry(tmp_path)

    # get_state should rebuild from journal
    state2 = await registry2.get_state(run_id)
    assert state2 is not None
    assert state2.run_id == run_id
    assert state2.status == RunStatus.routing


@pytest.mark.asyncio
async def test_registry_get_state_nonexistent_run(tmp_path):
    """get_state should return None for nonexistent runs."""
    registry = RunRegistry(tmp_path)

    state = await registry.get_state("nonexistent-run-id")
    assert state is None


@pytest.mark.asyncio
async def test_registry_rebuild_preserves_state(tmp_path):
    """Rebuilt state should match original state."""
    registry = RunRegistry(tmp_path)

    # Create run and route it
    state1 = await registry.create_run(objective="test rebuild")
    run_id = state1.run_id

    # Get orchestrator and route
    orch = registry._orchestrators[run_id]
    await orch.route()

    # Get current state
    original_state = registry._orchestrators[run_id].state

    # Simulate restart
    registry2 = RunRegistry(tmp_path)

    # Rebuild state
    rebuilt_state = await registry2.get_state(run_id)

    # Verify state matches
    assert rebuilt_state is not None
    assert rebuilt_state.run_id == original_state.run_id
    assert rebuilt_state.status == original_state.status


@pytest.mark.asyncio
async def test_registry_rebuild_caches_orchestrator(tmp_path):
    """After rebuild, orchestrator should be cached in registry."""
    registry = RunRegistry(tmp_path)

    # Create and route a run
    state1 = await registry.create_run(objective="test caching")
    run_id = state1.run_id

    # Simulate restart
    registry2 = RunRegistry(tmp_path)
    assert run_id not in registry2._orchestrators

    # First get_state rebuilds
    await registry2.get_state(run_id)
    assert run_id in registry2._orchestrators

    # Second get_state uses cached orchestrator
    state2 = await registry2.get_state(run_id)
    assert state2 is not None
    assert state2.run_id == run_id
