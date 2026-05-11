---
phase: 07-integrations
plan: 03
subsystem: integrations/sync
tags: [linear, sync, bidirectional, triggers, integration-tests]
dependency_graph:
  requires: [07-01, 07-02]
  provides: [bidirectional-linear-sync, sync-engine, integration-trigger-tests]
  affects: [task-lifecycle, webhook-processing]
tech_stack:
  added: []
  patterns: [state-mapping, entity-linking, sync-audit-log, end-to-end-trigger-flow]
key_files:
  created:
    - src/reins/integrations/sync.py
    - tests/unit/test_linear_sync.py
    - tests/integration/test_integration_triggers.py
  modified:
    - src/reins/integrations/linear.py
decisions:
  - SyncEngine uses in-memory dict for entity links (external_id -> task_id)
  - DEFAULT_MAPPINGS cover core Linear states with bidirectional direction
  - Inbound-only mappings for Backlog and Cancelled (no outbound equivalent in Reins)
  - LinearClient.sync_state_from_reins delegates to existing update_issue_status after mapping
  - Integration tests use real parser/engine instances with mock payloads (no HTTP mocking needed)
metrics:
  duration: 4m
  completed: 2026-05-11
  tests_added: 32
  tests_passing: 32
---

# Phase 7 Plan 03: Bidirectional Linear Sync and Integration Triggers

## Task 1: Bidirectional Linear Sync

Extended `LinearClient` with five new methods:
- `get_issue()` — query issue by ID via GraphQL
- `get_issue_state()` — returns current workflow state name
- `list_team_states()` — returns all team workflow states
- `sync_state_from_reins()` — maps Reins status to Linear state and updates
- `get_issues_by_label()` — query issues by label for agent-managed discovery

Created `SyncEngine` in `src/reins/integrations/sync.py`:
- Bidirectional state mapping with configurable `StateMapping` entries
- Entity linking (external_id <-> task_id)
- Sync event audit log with `SyncEvent` dataclass
- Direction-aware sync gating via `should_sync()`
- Factory method `create_sync_event()` for convenience

## Task 2: Integration Trigger End-to-End Tests

Created comprehensive integration tests covering:
- **GitHub flow**: issue labeled triggers spawn_run, PR merged triggers notify, no match without label
- **Linear flow**: state change triggers task update, sync maps states correctly, webhook extracts state
- **Approval flow**: request creates pending, response resolves, denial blocks
- **Full flow**: webhook -> trigger -> sync end-to-end, multiple triggers from single event, disabled triggers skipped

All 32 tests pass across both test files.
