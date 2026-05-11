"""Breadcrumb injection into agent context."""

from __future__ import annotations

from reins.workflow.breadcrumb import BreadcrumbGenerator
from reins.workflow.state_machine import WorkflowState, WorkflowStateMachine


class BreadcrumbInjector:
    """Injects workflow breadcrumbs into agent context.

    Wraps BreadcrumbGenerator to produce context-ready strings
    in plain text or XML format for structured injection.
    """

    def __init__(
        self,
        state_machine: WorkflowStateMachine | None = None,
        task_id: str | None = None,
    ) -> None:
        if state_machine is None:
            state_machine = WorkflowStateMachine()
        self._generator = BreadcrumbGenerator(state_machine, task_id=task_id)

    def inject(self) -> str:
        """Generate breadcrumb and format for context injection."""
        return self._generator.format_for_context()

    def inject_as_xml(self) -> str:
        """Wrap breadcrumb in XML tags for structured injection."""
        content = self._generator.format_for_context()
        return f"<workflow-breadcrumb>{content}</workflow-breadcrumb>"


def get_breadcrumb_for_task(task_id: str, state: WorkflowState | str) -> str:
    """Convenience function to get a formatted breadcrumb for a task.

    Creates a state machine, advances it to the given state (by replaying
    the default path), and returns the formatted breadcrumb string.

    Args:
        task_id: Identifier for the task.
        state: Target workflow state (enum or string value).

    Returns:
        Formatted breadcrumb string ready for context injection.
    """
    if isinstance(state, str):
        state = WorkflowState(state)

    sm = WorkflowStateMachine(initial_state=state)
    injector = BreadcrumbInjector(state_machine=sm, task_id=task_id)
    return injector.inject()
