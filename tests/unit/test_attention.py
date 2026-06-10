"""Tests for attention management with cognitive focus control."""

from __future__ import annotations

import pytest

from reins.attention import (
    AttentionBudget,
    AttentionItem,
    AttentionManager,
    AttentionPriority,
    AttentionShift,
    AttentionStats,
    FocusState,
    FocusWindow,
    StreamKind,
)


@pytest.fixture
def manager() -> AttentionManager:
    return AttentionManager(default_capacity=100.0)


def _item(stream=StreamKind.TASK, priority=AttentionPriority.NORMAL, content="test", weight=1.0):
    return AttentionItem(stream=stream, priority=priority, content=content, weight=weight)


def test_push_item_returns_state(manager):
    state = manager.push_item("agent-1", _item())
    assert state in FocusState


def test_push_item_transitions_from_idle(manager):
    state = manager.push_item("agent-1", _item())
    assert state != FocusState.IDLE


def test_focus_window_idle_initially(manager):
    window = manager.get_focus_window("agent-1")
    assert window.state == FocusState.IDLE
    assert len(window.items) == 0


def test_focus_window_after_push(manager):
    manager.push_item("agent-1", _item(content="do thing"))
    window = manager.get_focus_window("agent-1")
    assert len(window.items) == 1
    assert window.utilization > 0


def test_pop_item(manager):
    item = _item()
    manager.push_item("agent-1", item)
    assert manager.pop_item("agent-1", item.item_id)
    window = manager.get_focus_window("agent-1")
    assert len(window.items) == 0


def test_pop_item_not_found(manager):
    assert not manager.pop_item("agent-1", "nonexistent")


def test_pop_item_unknown_agent(manager):
    assert not manager.pop_item("unknown", "x")


def test_overloaded_state(manager):
    for i in range(20):
        manager.push_item("agent-1", _item(priority=AttentionPriority.CRITICAL, weight=2.0))
    window = manager.get_focus_window("agent-1")
    assert window.state == FocusState.OVERLOADED


def test_sharp_focus_few_streams(manager):
    manager.push_item("agent-1", _item(stream=StreamKind.TASK, weight=15.0))
    manager.push_item("agent-1", _item(stream=StreamKind.TASK, weight=15.0))
    window = manager.get_focus_window("agent-1")
    assert window.state == FocusState.SHARP


def test_diffuse_focus_high_utilization(manager):
    for i in range(10):
        stream = [StreamKind.TASK, StreamKind.ALERT, StreamKind.CONTEXT,
                  StreamKind.FEEDBACK, StreamKind.OBSERVATION][i % 5]
        manager.push_item("agent-1", _item(stream=stream, weight=3.0,
                                           priority=AttentionPriority.HIGH))
    window = manager.get_focus_window("agent-1")
    assert window.state in (FocusState.DIFFUSE, FocusState.OVERLOADED)


def test_get_budget(manager):
    manager.push_item("agent-1", _item(stream=StreamKind.TASK))
    budget = manager.get_budget("agent-1")
    assert budget.used > 0
    assert budget.available < budget.total_capacity
    assert StreamKind.TASK.value in budget.by_stream


def test_get_budget_empty(manager):
    budget = manager.get_budget("agent-1")
    assert budget.used == 0.0
    assert budget.available == 100.0


def test_get_top_items(manager):
    manager.push_item("agent-1", _item(priority=AttentionPriority.LOW, content="low"))
    manager.push_item("agent-1", _item(priority=AttentionPriority.CRITICAL, content="critical"))
    manager.push_item("agent-1", _item(priority=AttentionPriority.NORMAL, content="normal"))
    top = manager.get_top_items("agent-1", n=2)
    assert len(top) == 2
    assert top[0].content == "critical"


def test_get_top_items_empty(manager):
    assert manager.get_top_items("agent-1") == []


def test_decay_items(manager):
    item = _item(weight=0.15, content="ephemeral")
    item_high = AttentionItem(stream=StreamKind.TASK, priority=AttentionPriority.NORMAL,
                              content="ephemeral", weight=0.15, decay_rate=0.5)
    manager.push_item("agent-1", item_high)
    removed = manager.decay_items("agent-1")
    assert removed >= 0


def test_decay_removes_low_weight(manager):
    item = AttentionItem(stream=StreamKind.TASK, priority=AttentionPriority.LOW,
                         content="fading", weight=0.05, decay_rate=0.9)
    manager.push_item("agent-1", item)
    manager.decay_items("agent-1")
    window = manager.get_focus_window("agent-1")
    assert len(window.items) == 0


def test_decay_no_agent(manager):
    assert manager.decay_items("unknown") == 0


def test_clear_stream(manager):
    manager.push_item("agent-1", _item(stream=StreamKind.ALERT, content="a1"))
    manager.push_item("agent-1", _item(stream=StreamKind.ALERT, content="a2"))
    manager.push_item("agent-1", _item(stream=StreamKind.TASK, content="t1"))
    cleared = manager.clear_stream("agent-1", StreamKind.ALERT)
    assert cleared == 2
    window = manager.get_focus_window("agent-1")
    assert len(window.items) == 1


def test_clear_stream_empty(manager):
    assert manager.clear_stream("agent-1", StreamKind.ALERT) == 0


def test_shifts_recorded(manager):
    manager.push_item("agent-1", _item())
    shifts = manager.get_shifts(agent_id="agent-1")
    assert len(shifts) >= 1
    assert shifts[0].from_state == FocusState.IDLE


def test_shifts_filtered_by_agent(manager):
    manager.push_item("a", _item())
    manager.push_item("b", _item())
    shifts_a = manager.get_shifts(agent_id="a")
    shifts_b = manager.get_shifts(agent_id="b")
    assert all(s.agent_id == "a" for s in shifts_a)
    assert all(s.agent_id == "b" for s in shifts_b)


def test_priority_weights_affect_cost(manager):
    manager.push_item("a", _item(priority=AttentionPriority.CRITICAL, weight=1.0))
    manager.push_item("b", _item(priority=AttentionPriority.BACKGROUND, weight=1.0))
    budget_a = manager.get_budget("a")
    budget_b = manager.get_budget("b")
    assert budget_a.used > budget_b.used


def test_stats_empty():
    mgr = AttentionManager()
    stats = mgr.get_stats()
    assert stats.agents_tracked == 0
    assert stats.total_items == 0


def test_stats_with_data(manager):
    manager.push_item("agent-1", _item(stream=StreamKind.TASK, priority=AttentionPriority.HIGH))
    manager.push_item("agent-1", _item(stream=StreamKind.ALERT, priority=AttentionPriority.LOW))
    stats = manager.get_stats()
    assert stats.agents_tracked == 1
    assert stats.total_items == 2
    assert stats.by_priority["high"] == 1
    assert stats.by_stream["task"] == 1


def test_multiple_agents_independent(manager):
    manager.push_item("a", _item(content="x"))
    manager.push_item("b", _item(content="y"))
    window_a = manager.get_focus_window("a")
    window_b = manager.get_focus_window("b")
    assert len(window_a.items) == 1
    assert len(window_b.items) == 1


def test_state_returns_to_idle_after_clear(manager):
    item = _item()
    manager.push_item("agent-1", item)
    manager.pop_item("agent-1", item.item_id)
    window = manager.get_focus_window("agent-1")
    assert window.state == FocusState.IDLE
