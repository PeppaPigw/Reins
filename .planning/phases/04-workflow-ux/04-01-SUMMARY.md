---
phase: 04-workflow-ux
plan: 01
subsystem: workflow
tags: [state-machine, breadcrumb, context-injection]
dependency_graph:
  requires: []
  provides: [WorkflowStateMachine, BreadcrumbGenerator, BreadcrumbInjector]
  affects: [context-compilation, agent-turns]
tech_stack:
  added: []
  patterns: [frozen-dataclass, str-enum, configurable-transitions]
key_files:
  created:
    - src/reins/workflow/__init__.py
    - src/reins/workflow/state_machine.py
    - src/reins/workflow/breadcrumb.py
    - src/reins/context/breadcrumb_injection.py
    - tests/unit/test_workflow_state_machine.py
    - tests/unit/test_breadcrumb_injection.py
  modified: []
decisions:
  - "Used tuple for DEFAULT_TRANSITIONS (immutable, matches project conventions)"
  - "BreadcrumbInjector accepts optional state_machine to allow default construction"
  - "get_breadcrumb_for_task uses initial_state param rather than replaying transitions"
metrics:
  duration: "3 minutes"
  completed: "2026-05-11T07:29:00Z"
  tasks_completed: 2
  tasks_total: 2
  test_count: 20
---

# Phase 4 Plan 01: Workflow State Machine & Breadcrumbs Summary

Configurable workflow state machine with validated transitions and breadcrumb context injection for agent turns.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Create configurable workflow state machine | 5859949 | state_machine.py, test_workflow_state_machine.py |
| 2 | Create breadcrumb generation and context injection | b01183a | breadcrumb.py, breadcrumb_injection.py, test_breadcrumb_injection.py |

## Implementation Details

### Workflow State Machine

- `WorkflowState` enum: planning, in_progress, checking, blocked, done, cancelled
- `WorkflowTransition` frozen dataclass with from_state, to_state, trigger, guard
- `DEFAULT_TRANSITIONS` tuple with 9 transitions covering full lifecycle
- `WorkflowStateMachine` class: transition validation, history tracking, reset, configurable transitions
- `InvalidTransitionError` with from_state, trigger, and available_triggers for clear diagnostics

### Breadcrumb System

- `Breadcrumb` dataclass capturing task_id, current_state, available_transitions, history_summary
- `BreadcrumbGenerator` produces breadcrumbs from state machine, formats as compact context string
- `BreadcrumbInjector` wraps generator for plain text and XML injection into agent context
- `get_breadcrumb_for_task` convenience function for quick state-based lookups

## Deviations from Plan

None - plan executed exactly as written.

## Verification

- 20 tests pass (12 state machine + 8 breadcrumb)
- All imports resolve correctly
- Line counts exceed minimums (state_machine.py: 130+, breadcrumb.py: 80+, breadcrumb_injection.py: 55+)

## Self-Check: PASSED
