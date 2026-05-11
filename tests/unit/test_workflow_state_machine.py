"""Tests for the workflow state machine."""

from __future__ import annotations

import pytest

from reins.workflow.state_machine import (
    DEFAULT_TRANSITIONS,
    InvalidTransitionError,
    WorkflowState,
    WorkflowStateMachine,
    WorkflowTransition,
)


def test_initial_state_is_planning() -> None:
    sm = WorkflowStateMachine()
    assert sm.current_state == WorkflowState.planning


def test_transition_start_moves_to_in_progress() -> None:
    sm = WorkflowStateMachine()
    result = sm.transition("start")
    assert result == WorkflowState.in_progress
    assert sm.current_state == WorkflowState.in_progress


def test_full_happy_path() -> None:
    sm = WorkflowStateMachine()
    sm.transition("start")
    assert sm.current_state == WorkflowState.in_progress
    sm.transition("submit_for_review")
    assert sm.current_state == WorkflowState.checking
    sm.transition("approve")
    assert sm.current_state == WorkflowState.done


def test_invalid_transition_raises() -> None:
    sm = WorkflowStateMachine()
    with pytest.raises(InvalidTransitionError) as exc_info:
        sm.transition("approve")
    assert exc_info.value.from_state == WorkflowState.planning
    assert exc_info.value.trigger == "approve"
    assert "start" in exc_info.value.available_triggers


def test_available_transitions_from_planning() -> None:
    sm = WorkflowStateMachine()
    available = sm.available_transitions()
    triggers = [t.trigger for t in available]
    assert "start" in triggers
    assert "cancel" in triggers


def test_available_transitions_from_done() -> None:
    sm = WorkflowStateMachine()
    sm.transition("start")
    sm.transition("submit_for_review")
    sm.transition("approve")
    assert sm.current_state == WorkflowState.done
    available = sm.available_transitions()
    assert available == []


def test_can_transition_true_for_valid() -> None:
    sm = WorkflowStateMachine()
    assert sm.can_transition("start") is True


def test_can_transition_false_for_invalid() -> None:
    sm = WorkflowStateMachine()
    assert sm.can_transition("approve") is False


def test_history_tracks_transitions() -> None:
    sm = WorkflowStateMachine()
    sm.transition("start")
    sm.transition("submit_for_review")
    history = sm.history
    assert len(history) == 2
    assert history[0] == (WorkflowState.planning, "start", WorkflowState.in_progress)
    assert history[1] == (
        WorkflowState.in_progress,
        "submit_for_review",
        WorkflowState.checking,
    )


def test_reset_clears_state_and_history() -> None:
    sm = WorkflowStateMachine()
    sm.transition("start")
    sm.transition("submit_for_review")
    sm.reset()
    assert sm.current_state == WorkflowState.planning
    assert sm.history == []


def test_block_and_unblock_cycle() -> None:
    sm = WorkflowStateMachine()
    sm.transition("start")
    sm.transition("block")
    assert sm.current_state == WorkflowState.blocked
    sm.transition("unblock")
    assert sm.current_state == WorkflowState.in_progress


def test_custom_transitions() -> None:
    custom = (
        WorkflowTransition(
            from_state=WorkflowState.planning,
            to_state=WorkflowState.done,
            trigger="fast_track",
        ),
    )
    sm = WorkflowStateMachine(transitions=custom)
    sm.transition("fast_track")
    assert sm.current_state == WorkflowState.done
