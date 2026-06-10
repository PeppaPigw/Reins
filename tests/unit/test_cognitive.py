"""Tests for cognitive architecture with working memory and load modeling."""

from __future__ import annotations

import pytest

from reins.cognitive import (
    CognitiveArchitecture,
    CognitiveLoad,
    CognitiveProfile,
    CognitiveState,
    CognitiveStats,
    MemoryItem,
    MemoryKind,
    WorkingMemorySlot,
)


@pytest.fixture
def arch() -> CognitiveArchitecture:
    return CognitiveArchitecture(working_memory_capacity=5)


def test_store_memory(arch):
    item = arch.store_memory(MemoryKind.SEMANTIC, "Python is a language")
    assert arch.get_memory(item.item_id) is not None


def test_get_memory_not_found(arch):
    assert arch.get_memory("nonexistent") is None


def test_load_to_working_memory(arch):
    item = arch.store_memory(MemoryKind.WORKING, "task context")
    slot = arch.load_to_working_memory("agent-1", item.item_id)
    assert slot is not None
    assert slot.activation == 1.0


def test_load_nonexistent_item(arch):
    assert arch.load_to_working_memory("agent-1", "nonexistent") is None


def test_working_memory_capacity_limit(arch):
    items = []
    for i in range(7):
        item = arch.store_memory(MemoryKind.WORKING, f"item {i}")
        items.append(item)
        arch.load_to_working_memory("agent-1", item.item_id)
    slots = arch.get_working_memory("agent-1")
    assert len(slots) == 5


def test_working_memory_evicts_lowest_activation(arch):
    items = []
    for i in range(5):
        item = arch.store_memory(MemoryKind.WORKING, f"item {i}")
        items.append(item)
        arch.load_to_working_memory("agent-1", item.item_id)
    arch.rehearse("agent-1", items[2].item_id)
    arch.rehearse("agent-1", items[3].item_id)
    new_item = arch.store_memory(MemoryKind.WORKING, "new item")
    arch.load_to_working_memory("agent-1", new_item.item_id)
    slots = arch.get_working_memory("agent-1")
    item_ids = [s.item_id for s in slots]
    assert items[2].item_id in item_ids
    assert items[3].item_id in item_ids


def test_rehearse_increases_activation(arch):
    item = arch.store_memory(MemoryKind.WORKING, "important")
    arch.load_to_working_memory("agent-1", item.item_id)
    slot = arch.rehearse("agent-1", item.item_id)
    assert slot.rehearsals == 1


def test_rehearse_nonexistent(arch):
    assert arch.rehearse("agent-1", "nonexistent") is None


def test_clear_working_memory(arch):
    item = arch.store_memory(MemoryKind.WORKING, "temp")
    arch.load_to_working_memory("agent-1", item.item_id)
    arch.clear_working_memory("agent-1")
    assert len(arch.get_working_memory("agent-1")) == 0


def test_add_load(arch):
    arch.add_load("agent-1", CognitiveLoad.INTRINSIC, 1.0)
    profile = arch.get_profile("agent-1")
    assert profile.intrinsic_load == 1.0


def test_reduce_load(arch):
    arch.add_load("agent-1", CognitiveLoad.EXTRANEOUS, 2.0)
    arch.reduce_load("agent-1", CognitiveLoad.EXTRANEOUS, 1.0)
    profile = arch.get_profile("agent-1")
    assert profile.extraneous_load == 1.0


def test_reduce_load_floor(arch):
    arch.add_load("agent-1", CognitiveLoad.GERMANE, 1.0)
    arch.reduce_load("agent-1", CognitiveLoad.GERMANE, 5.0)
    profile = arch.get_profile("agent-1")
    assert profile.germane_load == 0.0


def test_state_idle(arch):
    assert arch.get_state("new-agent") == CognitiveState.IDLE


def test_state_focused(arch):
    arch.add_load("agent-1", CognitiveLoad.INTRINSIC, 1.0)
    assert arch.get_state("agent-1") == CognitiveState.FOCUSED


def test_state_overloaded(arch):
    arch.add_load("agent-1", CognitiveLoad.INTRINSIC, 2.0)
    arch.add_load("agent-1", CognitiveLoad.EXTRANEOUS, 2.0)
    assert arch.get_state("agent-1") == CognitiveState.OVERLOADED


def test_state_fatigued(arch):
    for _ in range(40):
        arch.add_load("agent-1", CognitiveLoad.INTRINSIC, 1.0)
    assert arch.get_state("agent-1") == CognitiveState.FATIGUED


def test_state_flow(arch):
    items = []
    for i in range(3):
        item = arch.store_memory(MemoryKind.WORKING, f"item {i}")
        items.append(item)
        arch.load_to_working_memory("agent-1", item.item_id)
    profile = arch.get_profile("agent-1")
    assert profile.state == CognitiveState.FLOW


def test_complete_task_reduces_fatigue(arch):
    arch.add_load("agent-1", CognitiveLoad.INTRINSIC, 5.0)
    fatigue_before = arch.get_profile("agent-1").fatigue_level
    arch.complete_task("agent-1")
    fatigue_after = arch.get_profile("agent-1").fatigue_level
    assert fatigue_after < fatigue_before


def test_rest_reduces_fatigue(arch):
    arch.add_load("agent-1", CognitiveLoad.INTRINSIC, 5.0)
    arch.rest("agent-1", amount=1.0)
    profile = arch.get_profile("agent-1")
    assert profile.fatigue_level < 0.25


def test_should_offload_high_load(arch):
    for i in range(5):
        item = arch.store_memory(MemoryKind.WORKING, f"item {i}")
        arch.load_to_working_memory("agent-1", item.item_id)
    assert arch.should_offload("agent-1")


def test_should_not_offload_low_load(arch):
    item = arch.store_memory(MemoryKind.WORKING, "single")
    arch.load_to_working_memory("agent-1", item.item_id)
    assert not arch.should_offload("agent-1")


def test_profile_complete(arch):
    arch.add_load("agent-1", CognitiveLoad.INTRINSIC, 0.5)
    item = arch.store_memory(MemoryKind.WORKING, "ctx")
    arch.load_to_working_memory("agent-1", item.item_id)
    profile = arch.get_profile("agent-1")
    assert profile.agent_id == "agent-1"
    assert profile.working_memory_capacity == 5
    assert profile.working_memory_load == pytest.approx(0.2)


def test_stats_empty():
    a = CognitiveArchitecture()
    stats = a.get_stats()
    assert stats.total_agents == 0


def test_stats_with_data(arch):
    arch.store_memory(MemoryKind.SEMANTIC, "fact1")
    arch.store_memory(MemoryKind.EPISODIC, "event1")
    arch.add_load("agent-1", CognitiveLoad.INTRINSIC, 1.0)
    arch.add_load("agent-2", CognitiveLoad.EXTRANEOUS, 0.5)
    stats = arch.get_stats()
    assert stats.total_agents == 2
    assert stats.total_memory_items == 2
    assert MemoryKind.SEMANTIC.value in stats.by_memory_kind
