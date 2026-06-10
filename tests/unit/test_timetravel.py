"""Tests for time-travel debugger."""

from __future__ import annotations

import pytest

from reins.testing.timetravel import TimeTravelDebugger, _get_nested
from reins.testing.timetravel_types import (
    DiffKind,
    TimelineQuery,
)


def counter_reducer(state: dict, event: dict) -> dict:
    new_state = dict(state)
    if event.get("type") == "increment":
        new_state["count"] = new_state.get("count", 0) + event.get("amount", 1)
    elif event.get("type") == "decrement":
        new_state["count"] = new_state.get("count", 0) - event.get("amount", 1)
    elif event.get("type") == "set_name":
        new_state["name"] = event.get("name", "")
    elif event.get("type") == "add_tag":
        tags = list(new_state.get("tags", []))
        tags.append(event.get("tag"))
        new_state["tags"] = tags
    elif event.get("type") == "remove_key":
        new_state.pop(event.get("key"), None)
    elif event.get("type") == "set_nested":
        if "nested" not in new_state:
            new_state["nested"] = {}
        new_state["nested"][event.get("key")] = event.get("value")
    return new_state


@pytest.fixture
def debugger() -> TimeTravelDebugger:
    return TimeTravelDebugger(counter_reducer)


@pytest.fixture
def loaded_debugger(debugger) -> TimeTravelDebugger:
    events = [
        {"type": "increment", "amount": 1},
        {"type": "increment", "amount": 5},
        {"type": "set_name", "name": "alpha"},
        {"type": "decrement", "amount": 2},
        {"type": "increment", "amount": 10},
    ]
    debugger.load_events(events, initial_state={"count": 0})
    return debugger


def test_load_events_builds_frames(loaded_debugger):
    assert loaded_debugger.event_count == 5
    assert loaded_debugger.frame_count == 5


def test_state_at_initial(loaded_debugger):
    state = loaded_debugger.state_at(0)
    assert state == {"count": 0}


def test_state_at_sequence(loaded_debugger):
    assert loaded_debugger.state_at(1) == {"count": 1}
    assert loaded_debugger.state_at(2) == {"count": 6}
    assert loaded_debugger.state_at(3) == {"count": 6, "name": "alpha"}
    assert loaded_debugger.state_at(4) == {"count": 4, "name": "alpha"}
    assert loaded_debugger.state_at(5) == {"count": 14, "name": "alpha"}


def test_state_at_out_of_range(loaded_debugger):
    with pytest.raises(IndexError):
        loaded_debugger.state_at(99)


def test_current_state(loaded_debugger):
    assert loaded_debugger.current_state() == {"count": 14, "name": "alpha"}


def test_current_state_empty(debugger):
    assert debugger.current_state() == {}


def test_append_event(loaded_debugger):
    frame = loaded_debugger.append_event({"type": "set_name", "name": "beta"})
    assert frame.sequence == 6
    assert loaded_debugger.current_state()["name"] == "beta"


def test_diff_added_key(loaded_debugger):
    diff = loaded_debugger.diff(2, 3)
    changes = {c.path: c for c in diff.changes}
    assert "name" in changes
    assert changes["name"].kind == DiffKind.ADDED
    assert changes["name"].new_value == "alpha"


def test_diff_modified_key(loaded_debugger):
    diff = loaded_debugger.diff(1, 2)
    changes = {c.path: c for c in diff.changes}
    assert "count" in changes
    assert changes["count"].kind == DiffKind.MODIFIED
    assert changes["count"].old_value == 1
    assert changes["count"].new_value == 6


def test_diff_removed_key(debugger):
    events = [
        {"type": "set_name", "name": "x"},
        {"type": "remove_key", "key": "name"},
    ]
    debugger.load_events(events, initial_state={})
    diff = debugger.diff(1, 2)
    changes = {c.path: c for c in diff.changes}
    assert "name" in changes
    assert changes["name"].kind == DiffKind.REMOVED


def test_diff_summary(loaded_debugger):
    diff = loaded_debugger.diff(0, 3)
    assert "modified" in diff.summary or "added" in diff.summary


def test_bisect_finds_threshold(loaded_debugger):
    result = loaded_debugger.bisect(
        lambda s: s.get("count", 0) >= 6,
        description="count >= 6",
    )
    assert result is not None
    assert result.found_at_sequence == 2
    assert result.event_type == "increment"
    assert result.predicate_description == "count >= 6"


def test_bisect_finds_key_appearance(loaded_debugger):
    result = loaded_debugger.bisect(
        lambda s: "name" in s,
        description="name key appears",
    )
    assert result is not None
    assert result.found_at_sequence == 3


def test_bisect_returns_none_when_never_true(loaded_debugger):
    result = loaded_debugger.bisect(lambda s: s.get("count", 0) > 100)
    assert result is None


def test_bisect_initial_state_true(debugger):
    debugger.load_events(
        [{"type": "increment", "amount": 1}],
        initial_state={"count": 99},
    )
    result = debugger.bisect(lambda s: s.get("count", 0) > 50)
    assert result is not None
    assert result.found_at_sequence == 0


def test_field_history_tracks_changes(loaded_debugger):
    query = TimelineQuery(field_path="count")
    history = loaded_debugger.field_history(query)
    assert len(history.changes) == 4
    assert history.changes[0].old_value == 0
    assert history.changes[0].new_value == 1


def test_field_history_with_range(loaded_debugger):
    query = TimelineQuery(field_path="count", from_sequence=3, to_sequence=4)
    history = loaded_debugger.field_history(query)
    assert len(history.changes) == 1
    assert history.changes[0].sequence == 4


def test_field_history_nested(debugger):
    events = [
        {"type": "set_nested", "key": "x", "value": 1},
        {"type": "set_nested", "key": "x", "value": 2},
        {"type": "set_nested", "key": "x", "value": 2},
    ]
    debugger.load_events(events, initial_state={})
    query = TimelineQuery(field_path="nested.x")
    history = debugger.field_history(query)
    assert len(history.changes) == 2
    assert history.changes[0].new_value == 1
    assert history.changes[1].new_value == 2


def test_checkpoint_and_restore(loaded_debugger):
    loaded_debugger.checkpoint("before_decrement", sequence=3)
    state = loaded_debugger.restore_checkpoint("before_decrement")
    assert state == {"count": 6, "name": "alpha"}


def test_checkpoint_default_sequence(loaded_debugger):
    cp = loaded_debugger.checkpoint("latest")
    assert cp.sequence == 5
    assert cp.state["count"] == 14


def test_restore_missing_checkpoint(loaded_debugger):
    with pytest.raises(KeyError):
        loaded_debugger.restore_checkpoint("nonexistent")


def test_list_checkpoints_sorted(loaded_debugger):
    loaded_debugger.checkpoint("c3", sequence=3)
    loaded_debugger.checkpoint("c1", sequence=1)
    loaded_debugger.checkpoint("c5", sequence=5)
    cps = loaded_debugger.list_checkpoints()
    assert [cp.sequence for cp in cps] == [1, 3, 5]


def test_find_events(loaded_debugger):
    frames = loaded_debugger.find_events("increment")
    assert len(frames) == 3


def test_slice(loaded_debugger):
    frames = loaded_debugger.slice(2, 4)
    assert len(frames) == 3
    assert frames[0].sequence == 2
    assert frames[-1].sequence == 4


def test_frame_at(loaded_debugger):
    frame = loaded_debugger.frame_at(3)
    assert frame.event_type == "set_name"
    assert frame.state["name"] == "alpha"


def test_frame_at_out_of_range(loaded_debugger):
    with pytest.raises(IndexError):
        loaded_debugger.frame_at(0)
    with pytest.raises(IndexError):
        loaded_debugger.frame_at(99)


def test_get_nested_helper():
    data = {"a": {"b": {"c": 42}}}
    assert _get_nested(data, "a.b.c") == 42
    assert _get_nested(data, "a.b") == {"c": 42}
    assert _get_nested(data, "x.y.z") is None
