"""Breadcrumb generation from workflow state machine."""

from __future__ import annotations

from dataclasses import dataclass, field

from reins.workflow.state_machine import WorkflowState, WorkflowStateMachine


@dataclass
class Breadcrumb:
    """A snapshot of workflow state formatted for context injection."""

    task_id: str | None
    current_state: WorkflowState
    available_transitions: list[str]
    history_summary: str
    metadata: dict[str, str] = field(default_factory=dict)


class BreadcrumbGenerator:
    """Generates breadcrumbs from a workflow state machine instance.

    Breadcrumbs provide a compact representation of the current workflow
    state, available transitions, and recent history for injection into
    agent context.
    """

    def __init__(
        self,
        state_machine: WorkflowStateMachine,
        task_id: str | None = None,
    ) -> None:
        self._state_machine = state_machine
        self._task_id = task_id

    def generate(self) -> Breadcrumb:
        """Build a breadcrumb from the current state machine state."""
        available = [t.trigger for t in self._state_machine.available_transitions()]
        history_summary = self._build_history_summary()
        return Breadcrumb(
            task_id=self._task_id,
            current_state=self._state_machine.current_state,
            available_transitions=available,
            history_summary=history_summary,
        )

    def format_for_context(self) -> str:
        """Render breadcrumb as a compact string for context injection.

        Format:
            [workflow-state:{state}] transitions: {triggers} | history: {path}
        """
        breadcrumb = self.generate()
        triggers = ", ".join(breadcrumb.available_transitions) or "none"
        history = breadcrumb.history_summary or "none"
        return (
            f"[workflow-state:{breadcrumb.current_state.value}] "
            f"transitions: {triggers} | history: {history}"
        )

    def _build_history_summary(self) -> str:
        """Build a summary of the last 3 transitions as a path string."""
        history = self._state_machine.history
        if not history:
            return ""
        # Take last 3 transitions and build a path
        recent = history[-3:]
        parts = [recent[0][0].value]
        for _, _, to_state in recent:
            parts.append(to_state.value)
        return "->".join(parts)
