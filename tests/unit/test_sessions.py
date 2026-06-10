"""Tests for session types: formal agent communication contracts."""

from __future__ import annotations

import pytest

from reins.sessions import (
    Direction,
    MessageSpec,
    ProtocolViolation,
    SessionChecker,
    SessionProtocol,
    SessionState,
    SessionTypeError,
)


@pytest.fixture
def checker() -> SessionChecker:
    return SessionChecker()


@pytest.fixture
def request_response_protocol() -> SessionProtocol:
    return SessionProtocol(
        name="request-response",
        description="Simple request/response between two agents",
        initial_state="start",
        terminal_states=("end",),
        transitions={
            "start": (
                MessageSpec(direction=Direction.SEND, label="request", next_states=("awaiting",)),
            ),
            "awaiting": (
                MessageSpec(direction=Direction.RECV, label="response", next_states=("end",)),
            ),
        },
    )


@pytest.fixture
def task_delegation_protocol() -> SessionProtocol:
    return SessionProtocol(
        name="task-delegation",
        description="Orchestrator delegates task to worker with status updates",
        initial_state="idle",
        terminal_states=("done", "failed"),
        transitions={
            "idle": (
                MessageSpec(direction=Direction.SEND, label="assign", next_states=("working",)),
            ),
            "working": (
                MessageSpec(direction=Direction.RECV, label="progress", next_states=("working",)),
                MessageSpec(direction=Direction.RECV, label="complete", next_states=("done",)),
                MessageSpec(direction=Direction.RECV, label="error", next_states=("failed",)),
            ),
        },
    )


def test_register_and_begin_session(checker, request_response_protocol):
    checker.register_protocol(request_response_protocol)
    state = checker.begin_session("request-response")
    assert state.current_state == "start"
    assert state.protocol_name == "request-response"
    assert not state.is_terminated


def test_begin_unknown_protocol_raises(checker):
    with pytest.raises(ValueError, match="Unknown protocol"):
        checker.begin_session("nonexistent")


def test_valid_request_response_flow(checker, request_response_protocol):
    checker.register_protocol(request_response_protocol)
    state = checker.begin_session("request-response")

    state = checker.advance(state.session_id, Direction.SEND, "request")
    assert state.current_state == "awaiting"

    state = checker.advance(state.session_id, Direction.RECV, "response")
    assert state.current_state == "end"
    assert state.is_terminated


def test_protocol_violation_wrong_direction(checker, request_response_protocol):
    checker.register_protocol(request_response_protocol)
    state = checker.begin_session("request-response")

    with pytest.raises(SessionTypeError) as exc_info:
        checker.advance(state.session_id, Direction.RECV, "request")

    violation = exc_info.value.violation
    assert violation.actual_direction == Direction.RECV
    assert violation.current_state == "start"


def test_protocol_violation_wrong_label(checker, request_response_protocol):
    checker.register_protocol(request_response_protocol)
    state = checker.begin_session("request-response")

    with pytest.raises(SessionTypeError) as exc_info:
        checker.advance(state.session_id, Direction.SEND, "wrong_label")

    assert "wrong_label" in exc_info.value.violation.message


def test_cannot_advance_terminated_session(checker, request_response_protocol):
    checker.register_protocol(request_response_protocol)
    state = checker.begin_session("request-response")
    checker.advance(state.session_id, Direction.SEND, "request")
    checker.advance(state.session_id, Direction.RECV, "response")

    with pytest.raises(SessionTypeError) as exc_info:
        checker.advance(state.session_id, Direction.SEND, "request")

    assert "terminated" in exc_info.value.violation.message


def test_task_delegation_happy_path(checker, task_delegation_protocol):
    checker.register_protocol(task_delegation_protocol)
    state = checker.begin_session("task-delegation")

    state = checker.advance(state.session_id, Direction.SEND, "assign")
    assert state.current_state == "working"

    state = checker.advance(state.session_id, Direction.RECV, "progress")
    assert state.current_state == "working"

    state = checker.advance(state.session_id, Direction.RECV, "progress")
    assert state.current_state == "working"

    state = checker.advance(state.session_id, Direction.RECV, "complete")
    assert state.current_state == "done"
    assert state.is_terminated


def test_task_delegation_failure_path(checker, task_delegation_protocol):
    checker.register_protocol(task_delegation_protocol)
    state = checker.begin_session("task-delegation")

    checker.advance(state.session_id, Direction.SEND, "assign")
    state = checker.advance(state.session_id, Direction.RECV, "error")
    assert state.current_state == "failed"
    assert state.is_terminated


def test_validate_complete(checker, request_response_protocol):
    checker.register_protocol(request_response_protocol)
    state = checker.begin_session("request-response")

    assert not checker.validate_complete(state.session_id)

    checker.advance(state.session_id, Direction.SEND, "request")
    assert not checker.validate_complete(state.session_id)

    checker.advance(state.session_id, Direction.RECV, "response")
    assert checker.validate_complete(state.session_id)


def test_get_allowed_actions(checker, task_delegation_protocol):
    checker.register_protocol(task_delegation_protocol)
    state = checker.begin_session("task-delegation")

    actions = checker.get_allowed_actions(state.session_id)
    assert (Direction.SEND, "assign") in actions

    checker.advance(state.session_id, Direction.SEND, "assign")
    actions = checker.get_allowed_actions(state.session_id)
    assert (Direction.RECV, "progress") in actions
    assert (Direction.RECV, "complete") in actions
    assert (Direction.RECV, "error") in actions


def test_terminated_session_has_no_actions(checker, request_response_protocol):
    checker.register_protocol(request_response_protocol)
    state = checker.begin_session("request-response")
    checker.advance(state.session_id, Direction.SEND, "request")
    checker.advance(state.session_id, Direction.RECV, "response")

    actions = checker.get_allowed_actions(state.session_id)
    assert actions == []


def test_history_tracks_transitions(checker, task_delegation_protocol):
    checker.register_protocol(task_delegation_protocol)
    state = checker.begin_session("task-delegation")

    checker.advance(state.session_id, Direction.SEND, "assign")
    checker.advance(state.session_id, Direction.RECV, "progress")
    state = checker.advance(state.session_id, Direction.RECV, "complete")

    assert state.history == ("send(assign)", "recv(progress)", "recv(complete)")


def test_get_session(checker, request_response_protocol):
    checker.register_protocol(request_response_protocol)
    state = checker.begin_session("request-response")

    retrieved = checker.get_session(state.session_id)
    assert retrieved is not None
    assert retrieved.session_id == state.session_id


def test_get_unknown_session(checker):
    assert checker.get_session("nonexistent") is None


def test_unknown_session_advance_raises(checker):
    with pytest.raises(ValueError, match="Unknown session"):
        checker.advance("fake-id", Direction.SEND, "msg")
