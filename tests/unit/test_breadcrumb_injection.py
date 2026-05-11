"""Tests for breadcrumb generation and context injection."""

from __future__ import annotations

from reins.context.breadcrumb_injection import BreadcrumbInjector, get_breadcrumb_for_task
from reins.workflow.breadcrumb import Breadcrumb, BreadcrumbGenerator
from reins.workflow.state_machine import WorkflowState, WorkflowStateMachine


def test_breadcrumb_generator_produces_breadcrumb() -> None:
    sm = WorkflowStateMachine()
    gen = BreadcrumbGenerator(sm, task_id="task-1")
    breadcrumb = gen.generate()
    assert isinstance(breadcrumb, Breadcrumb)
    assert breadcrumb.task_id == "task-1"
    assert breadcrumb.current_state == WorkflowState.planning


def test_format_for_context_includes_state() -> None:
    sm = WorkflowStateMachine()
    gen = BreadcrumbGenerator(sm)
    result = gen.format_for_context()
    assert "workflow-state:planning" in result


def test_format_for_context_includes_transitions() -> None:
    sm = WorkflowStateMachine()
    gen = BreadcrumbGenerator(sm)
    result = gen.format_for_context()
    assert "start" in result
    assert "cancel" in result


def test_format_for_context_includes_history() -> None:
    sm = WorkflowStateMachine()
    sm.transition("start")
    gen = BreadcrumbGenerator(sm)
    result = gen.format_for_context()
    assert "planning->in_progress" in result


def test_injector_inject_returns_string() -> None:
    sm = WorkflowStateMachine()
    injector = BreadcrumbInjector(state_machine=sm, task_id="task-2")
    result = injector.inject()
    assert isinstance(result, str)
    assert "workflow-state:planning" in result


def test_injector_inject_as_xml_has_tags() -> None:
    sm = WorkflowStateMachine()
    injector = BreadcrumbInjector(state_machine=sm)
    result = injector.inject_as_xml()
    assert result.startswith("<workflow-breadcrumb>")
    assert result.endswith("</workflow-breadcrumb>")
    assert "workflow-state:planning" in result


def test_get_breadcrumb_for_task_convenience() -> None:
    result = get_breadcrumb_for_task("task-3", "in_progress")
    assert "workflow-state:in_progress" in result
    assert "submit_for_review" in result


def test_breadcrumb_with_no_history() -> None:
    sm = WorkflowStateMachine()
    gen = BreadcrumbGenerator(sm)
    breadcrumb = gen.generate()
    assert breadcrumb.history_summary == ""
    result = gen.format_for_context()
    assert "history: none" in result
