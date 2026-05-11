"""Configurable workflow state machine with validated transitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class WorkflowState(str, Enum):
    """States a workflow task can be in."""

    planning = "planning"
    in_progress = "in_progress"
    checking = "checking"
    blocked = "blocked"
    done = "done"
    cancelled = "cancelled"


class InvalidTransitionError(ValueError):
    """Raised when a transition is not valid from the current state."""

    def __init__(
        self,
        from_state: WorkflowState,
        trigger: str,
        available_triggers: list[str],
    ) -> None:
        self.from_state = from_state
        self.trigger = trigger
        self.available_triggers = available_triggers
        available = ", ".join(available_triggers) if available_triggers else "none"
        super().__init__(
            f"Invalid transition: trigger '{trigger}' is not valid from state "
            f"'{from_state.value}'. Available triggers: {available}"
        )


@dataclass(frozen=True)
class WorkflowTransition:
    """A single allowed transition between workflow states."""

    from_state: WorkflowState
    to_state: WorkflowState
    trigger: str
    guard: str | None = None


DEFAULT_TRANSITIONS: tuple[WorkflowTransition, ...] = (
    WorkflowTransition(
        from_state=WorkflowState.planning,
        to_state=WorkflowState.in_progress,
        trigger="start",
    ),
    WorkflowTransition(
        from_state=WorkflowState.in_progress,
        to_state=WorkflowState.checking,
        trigger="submit_for_review",
    ),
    WorkflowTransition(
        from_state=WorkflowState.checking,
        to_state=WorkflowState.in_progress,
        trigger="request_changes",
    ),
    WorkflowTransition(
        from_state=WorkflowState.checking,
        to_state=WorkflowState.done,
        trigger="approve",
    ),
    WorkflowTransition(
        from_state=WorkflowState.in_progress,
        to_state=WorkflowState.blocked,
        trigger="block",
    ),
    WorkflowTransition(
        from_state=WorkflowState.blocked,
        to_state=WorkflowState.in_progress,
        trigger="unblock",
    ),
    WorkflowTransition(
        from_state=WorkflowState.planning,
        to_state=WorkflowState.cancelled,
        trigger="cancel",
    ),
    WorkflowTransition(
        from_state=WorkflowState.in_progress,
        to_state=WorkflowState.cancelled,
        trigger="cancel",
    ),
    WorkflowTransition(
        from_state=WorkflowState.blocked,
        to_state=WorkflowState.cancelled,
        trigger="cancel",
    ),
)


class WorkflowStateMachine:
    """Configurable state machine for workflow lifecycle management.

    Tracks current state, validates transitions against a configured set,
    and maintains a history of all transitions taken.
    """

    def __init__(
        self,
        transitions: tuple[WorkflowTransition, ...] = DEFAULT_TRANSITIONS,
        initial_state: WorkflowState = WorkflowState.planning,
    ) -> None:
        self._transitions = transitions
        self._initial_state = initial_state
        self.current_state = initial_state
        self._history: list[tuple[WorkflowState, str, WorkflowState]] = []

    def available_transitions(self) -> list[WorkflowTransition]:
        """Return valid transitions from the current state."""
        return [t for t in self._transitions if t.from_state == self.current_state]

    def can_transition(self, trigger: str) -> bool:
        """Check if a trigger is valid from the current state."""
        return any(
            t.trigger == trigger
            for t in self._transitions
            if t.from_state == self.current_state
        )

    def transition(self, trigger: str) -> WorkflowState:
        """Execute a transition by trigger name.

        Returns the new state after transition.
        Raises InvalidTransitionError if the trigger is not valid from the current state.
        """
        for t in self._transitions:
            if t.from_state == self.current_state and t.trigger == trigger:
                from_state = self.current_state
                self.current_state = t.to_state
                self._history.append((from_state, trigger, t.to_state))
                return self.current_state

        available = [t.trigger for t in self.available_transitions()]
        raise InvalidTransitionError(self.current_state, trigger, available)

    @property
    def history(self) -> list[tuple[WorkflowState, str, WorkflowState]]:
        """Return the full transition history as (from_state, trigger, to_state) tuples."""
        return list(self._history)

    def reset(self) -> None:
        """Reset to initial state and clear history."""
        self.current_state = self._initial_state
        self._history.clear()
