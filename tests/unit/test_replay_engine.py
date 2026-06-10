"""Tests for deterministic replay engine."""

from __future__ import annotations

import pytest

from reins.replay import (
    Breakpoint,
    Divergence,
    EventRecord,
    ReplayEngine,
    ReplayMode,
    ReplaySession,
    ReplayStats,
    ReplayStatus,
)


@pytest.fixture
def engine() -> ReplayEngine:
    return ReplayEngine()


def test_record_event(engine):
    event = engine.record("run-1", "agent-a", "task.started",
                          payload={"task": "review"})
    assert event.sequence == 0
    assert event.agent_id == "agent-a"
    assert event.event_type == "task.started"


def test_record_sequential(engine):
    engine.record("run-1", "a", "start")
    engine.record("run-1", "a", "middle")
    engine.record("run-1", "a", "end")
    events = engine.get_events("run-1")
    assert len(events) == 3
    assert events[0].sequence == 0
    assert events[2].sequence == 2


def test_record_with_state_hash(engine):
    event = engine.record("run-1", "a", "update",
                          state={"counter": 1})
    assert event.state_hash != ""


def test_get_events_empty(engine):
    assert engine.get_events("nonexistent") == []


def test_start_replay(engine):
    engine.record("run-1", "a", "start")
    engine.record("run-1", "a", "end")
    session = engine.start_replay("run-1")
    assert session is not None
    assert session.status == ReplayStatus.RUNNING
    assert session.total_events == 2


def test_start_replay_empty_run(engine):
    assert engine.start_replay("nonexistent") is None


def test_step_through_events(engine):
    engine.record("run-1", "a", "init", payload={"x": 1})
    engine.record("run-1", "a", "update", payload={"y": 2})
    session = engine.start_replay("run-1")
    event, state = engine.step(session.session_id, {})
    assert event.event_type == "init"
    assert state["x"] == 1
    event, state = engine.step(session.session_id, state)
    assert event.event_type == "update"
    assert state["y"] == 2


def test_step_completes(engine):
    engine.record("run-1", "a", "only", payload={"done": True})
    session = engine.start_replay("run-1")
    engine.step(session.session_id, {})
    event, state = engine.step(session.session_id, state={})
    assert event is None
    updated = engine.get_session(session.session_id)
    assert updated.status == ReplayStatus.COMPLETED


def test_step_invalid_session(engine):
    event, state = engine.step("nonexistent", {})
    assert event is None


def test_replay_all(engine):
    engine.record("run-1", "a", "set_x", payload={"x": 10})
    engine.record("run-1", "a", "set_y", payload={"y": 20})
    session = engine.start_replay("run-1")
    final = engine.replay_all(session.session_id, initial_state={})
    assert final["x"] == 10
    assert final["y"] == 20


def test_replay_with_custom_reducer(engine):
    def reducer(state, event):
        if event.event_type == "increment":
            return {**state, "count": state.get("count", 0) + event.payload["n"]}
        return state

    engine.set_reducer(reducer)
    engine.record("run-1", "a", "increment", payload={"n": 5})
    engine.record("run-1", "a", "increment", payload={"n": 3})
    session = engine.start_replay("run-1")
    final = engine.replay_all(session.session_id, {"count": 0})
    assert final["count"] == 8


def test_divergence_detection(engine):
    engine.record("run-1", "a", "set", payload={"val": 1},
                  state={"val": 1})
    engine.record("run-1", "a", "set", payload={"val": 2},
                  state={"val": 999})
    session = engine.start_replay("run-1")
    engine.step(session.session_id, {})
    event, state = engine.step(session.session_id, {"val": 1})
    updated = engine.get_session(session.session_id)
    assert updated.status == ReplayStatus.DIVERGED
    assert updated.divergence_point == 1
    divergences = engine.get_divergences()
    assert len(divergences) == 1


def test_breakpoint_at_sequence(engine):
    engine.record("run-1", "a", "step0", payload={"i": 0})
    engine.record("run-1", "a", "step1", payload={"i": 1})
    engine.record("run-1", "a", "step2", payload={"i": 2})
    session = engine.start_replay("run-1")
    engine.add_breakpoint(session.session_id, at_sequence=1)
    engine.step(session.session_id, {})
    engine.step(session.session_id, {"i": 0})
    updated = engine.get_session(session.session_id)
    assert updated.status == ReplayStatus.PAUSED


def test_breakpoint_at_event_type(engine):
    engine.record("run-1", "a", "init", payload={})
    engine.record("run-1", "a", "error", payload={"msg": "fail"})
    session = engine.start_replay("run-1")
    engine.add_breakpoint(session.session_id, at_event_type="error")
    engine.step(session.session_id, {})
    engine.step(session.session_id, {})
    updated = engine.get_session(session.session_id)
    assert updated.status == ReplayStatus.PAUSED


def test_breakpoint_at_agent(engine):
    engine.record("run-1", "agent-a", "work", payload={})
    engine.record("run-1", "agent-b", "work", payload={})
    session = engine.start_replay("run-1")
    engine.add_breakpoint(session.session_id, at_agent="agent-b")
    engine.step(session.session_id, {})
    engine.step(session.session_id, {})
    updated = engine.get_session(session.session_id)
    assert updated.status == ReplayStatus.PAUSED


def test_resume_after_breakpoint(engine):
    engine.record("run-1", "a", "step0", payload={"i": 0})
    engine.record("run-1", "a", "step1", payload={"i": 1})
    session = engine.start_replay("run-1")
    engine.add_breakpoint(session.session_id, at_sequence=0)
    engine.step(session.session_id, {})
    assert engine.get_session(session.session_id).status == ReplayStatus.PAUSED
    assert engine.resume(session.session_id) is True
    assert engine.get_session(session.session_id).status == ReplayStatus.RUNNING


def test_resume_not_paused(engine):
    engine.record("run-1", "a", "x", payload={})
    session = engine.start_replay("run-1")
    assert engine.resume(session.session_id) is False


def test_remove_breakpoint(engine):
    engine.record("run-1", "a", "x", payload={})
    session = engine.start_replay("run-1")
    bp = engine.add_breakpoint(session.session_id, at_sequence=0)
    assert engine.remove_breakpoint(session.session_id, bp.breakpoint_id) is True
    assert engine.remove_breakpoint(session.session_id, "nonexistent") is False


def test_stats_empty(engine):
    stats = engine.get_stats()
    assert stats.total_sessions == 0


def test_stats_populated(engine):
    engine.record("run-1", "a", "x", payload={"v": 1})
    engine.record("run-1", "a", "y", payload={"v": 2})
    s = engine.start_replay("run-1")
    engine.replay_all(s.session_id, {})
    stats = engine.get_stats()
    assert stats.total_sessions == 1
    assert stats.completed_sessions == 1
    assert stats.total_events_replayed == 2
    assert stats.by_mode["full"] == 1


def test_multiple_runs_isolated(engine):
    engine.record("run-a", "a", "x", payload={"a": 1})
    engine.record("run-b", "b", "y", payload={"b": 2})
    assert len(engine.get_events("run-a")) == 1
    assert len(engine.get_events("run-b")) == 1


def test_replay_modes(engine):
    engine.record("run-1", "a", "x", payload={})
    for mode in ReplayMode:
        session = engine.start_replay("run-1", mode=mode)
        assert session.mode == mode
