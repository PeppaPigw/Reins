# Reins Development Roadmap - Detailed Task Breakdown

## Phase 4: CLI Commands for Task and Spec Management

### Task 4.1: CLI Framework Setup
- [ ] Install dependencies (typer, rich, tabulate)
- [ ] Create `src/reins/cli/__init__.py` entry point
- [ ] Create `src/reins/cli/main.py` command dispatcher
- [ ] Create `src/reins/cli/utils.py` shared utilities
- [ ] Implement `find_repo_root()` helper
- [ ] Implement `load_config()` helper
- [ ] Implement `format_timestamp()` helper
- [ ] Implement `format_table()` helper
- [ ] Add CLI tests: `tests/unit/test_cli_utils.py`

### Task 4.2: Task Lifecycle Commands
- [ ] Create `src/reins/cli/commands/task.py`
- [ ] Implement `reins task create` command
- [ ] Implement `reins task list` command
- [ ] Implement `reins task show` command
- [ ] Implement `reins task start` command
- [ ] Implement `reins task finish` command
- [ ] Implement `reins task archive` command
- [ ] Emit events: `task.created`, `task.started`, `task.finished`, `task.archived`
- [ ] Update `.reins/.current-task` pointer
- [ ] Add tests: `tests/unit/test_cli_task.py`

### Task 4.3: Task Context Commands
- [ ] Create `src/reins/cli/commands/task_context.py`
- [ ] Implement `reins task add-context` command
- [ ] Implement `reins task init-context` command
- [ ] Handle JSONL file operations (implement.jsonl, check.jsonl, debug.jsonl)
- [ ] Validate JSONL format
- [ ] Add tests: `tests/unit/test_cli_task_context.py`

### Task 4.4: Spec Management Commands
- [ ] Create `src/reins/cli/commands/spec.py`
- [ ] Implement `reins spec init` command
- [ ] Implement `reins spec list` command
- [ ] Implement `reins spec validate` command
- [ ] Implement `reins spec add-layer` command
- [ ] Generate index.md with Pre-Development Checklist template
- [ ] Add tests: `tests/unit/test_cli_spec.py`

### Task 4.5: Developer Identity Commands
- [ ] Create `src/reins/cli/commands/developer.py`
- [ ] Implement `reins developer init` command
- [ ] Implement `reins developer show` command
- [ ] Implement `reins developer workspace-info` command
- [ ] Create `.reins/.developer` file
- [ ] Initialize workspace directory structure
- [ ] Add tests: `tests/unit/test_cli_developer.py`

### Task 4.6: Migration Commands
- [ ] Create `src/reins/cli/commands/migrate.py`
- [ ] Implement `reins migrate run` command
- [ ] Implement `reins migrate list` command
- [ ] Implement `reins migrate validate` command
- [ ] Implement `reins migrate create` command
- [ ] Integrate with `MigrationEngine` from Phase 3
- [ ] Support dry-run mode
- [ ] Add tests: `tests/unit/test_cli_migrate.py`

### Task 4.7: Worktree Commands
- [ ] Create `src/reins/cli/commands/worktree.py`
- [ ] Implement `reins worktree create` command
- [ ] Implement `reins worktree list` command
- [ ] Implement `reins worktree verify` command
- [ ] Implement `reins worktree cleanup` command
- [ ] Implement `reins worktree cleanup-orphans` command
- [ ] Integrate with `WorktreeManager` from Phase 3
- [ ] Add tests: `tests/unit/test_cli_worktree.py`

### Task 4.8: Journal Commands
- [ ] Create `src/reins/cli/commands/journal.py`
- [ ] Implement `reins journal show` command
- [ ] Implement `reins journal replay` command
- [ ] Implement `reins journal export` command
- [ ] Implement `reins journal stats` command
- [ ] Support filtering by event type, timestamp, actor
- [ ] Add tests: `tests/unit/test_cli_journal.py`

### Task 4.9: Status Commands
- [ ] Create `src/reins/cli/commands/status.py`
- [ ] Implement `reins status` command
- [ ] Show current task
- [ ] Show active agents from registry
- [ ] Show git status
- [ ] Show recent journal events
- [ ] Show workspace info
- [ ] Add tests: `tests/unit/test_cli_status.py`

### Task 4.10: CLI Integration Test
- [ ] Create `tests/integration/test_cli_workflows.py`
- [ ] Test complete workflow: create → start → finish → archive
- [ ] Test context management workflow
- [ ] Test spec initialization workflow
- [ ] Test migration workflow
- [ ] Test worktree workflow
- [ ] Verify all commands emit correct events
- [ ] Verify file system state after each command

### Task 4.11: CLI Documentation
- [ ] Create `.reins/spec/cli/index.md`
- [ ] Document all command groups
- [ ] Add usage examples for each command
- [ ] Document error messages and troubleshooting
- [ ] Add command reference table

---

## Phase 5: Integration Tests for End-to-End Workflows

### Task 5.1: Test Infrastructure Setup
- [ ] Create `tests/integration/conftest.py` with fixtures
- [ ] Implement `temp_repo` fixture
- [ ] Implement `mock_adapter` fixture
- [ ] Implement `test_config` fixture
- [ ] Create `tests/integration/helpers.py`
- [ ] Implement `wait_for_event()` helper
- [ ] Implement `verify_journal_sequence()` helper
- [ ] Implement `create_test_task()` helper
- [ ] Implement `simulate_agent_work()` helper

### Task 5.2: Task Lifecycle Integration Test
- [ ] Create `tests/integration/test_task_lifecycle.py`
- [ ] Test task creation with CLI
- [ ] Test task directory structure
- [ ] Test `task.created` event emission
- [ ] Test task start (`.current-task` update)
- [ ] Test context file addition
- [ ] Test task finish
- [ ] Test task archive
- [ ] Verify complete event sequence

### Task 5.3: Spec Injection Integration Test
- [ ] Create `tests/integration/test_spec_injection.py`
- [ ] Test spec structure initialization
- [ ] Test task with package assignment
- [ ] Test `init-context` command
- [ ] Test default spec files in JSONL
- [ ] Test custom spec file addition
- [ ] Test hook reading JSONL
- [ ] Verify spec content injection

### Task 5.4: Worktree Parallel Execution Test
- [ ] Create `tests/integration/test_worktree_parallel.py`
- [ ] Test creating 3 worktrees in parallel
- [ ] Verify separate git branches
- [ ] Verify `.developer` file copied
- [ ] Verify task pointers set correctly
- [ ] Verify agents registered
- [ ] Test post-create hooks
- [ ] Test verification hooks
- [ ] Test cleanup and unregistration

### Task 5.5: Migration System Integration Test
- [ ] Create `tests/integration/test_migration_system.py`
- [ ] Test migration with dry-run
- [ ] Test actual migration execution
- [ ] Test file operations (rename, delete, safe-delete)
- [ ] Test migration events in journal
- [ ] Test idempotency (run twice)
- [ ] Test rollback on failure
- [ ] Verify safe-file-delete protects modified files

### Task 5.6: Event Sourcing Integration Test
- [ ] Create `tests/integration/test_event_sourcing.py`
- [ ] Test sequence of operations
- [ ] Test event emission for all operations
- [ ] Test journal event ordering
- [ ] Test event replay
- [ ] Test state reconstruction from events
- [ ] Test reducer purity

### Task 5.7: Multi-Agent Coordination Test
- [ ] Create `tests/integration/test_multi_agent.py`
- [ ] Test parent task with subtasks
- [ ] Test worktree creation for each subtask
- [ ] Test parallel agent simulation
- [ ] Test agent isolation
- [ ] Test registry heartbeat tracking
- [ ] Test partial failure handling
- [ ] Test cleanup safety

### Task 5.8: Policy Engine Integration Test
- [ ] Create `tests/integration/test_policy_engine.py`
- [ ] Test command proposals with different risk tiers
- [ ] Test policy evaluation
- [ ] Test grant issuance
- [ ] Test rejection with reason
- [ ] Test policy decisions in journal
- [ ] Test capability taxonomy lookup

### Task 5.9: Checkpoint/Resume Integration Test
- [ ] Create `tests/integration/test_checkpoint_resume.py`
- [ ] Test checkpoint creation mid-execution
- [ ] Test checkpoint manifest saving
- [ ] Test process interruption simulation
- [ ] Test resume from checkpoint
- [ ] Test state restoration
- [ ] Test work continuation
- [ ] Test checkpoint/resume events

### Task 5.10: Error Handling Integration Test
- [ ] Create `tests/integration/test_error_handling.py`
- [ ] Test missing file scenarios
- [ ] Test invalid JSON handling
- [ ] Test corrupted journal handling
- [ ] Test git worktree failures
- [ ] Test migration rollback on error
- [ ] Test agent registration conflicts
- [ ] Test error events in journal
- [ ] Verify state consistency after errors

### Task 5.11: Full Workflow Integration Test
- [ ] Create `tests/integration/test_full_workflow.py`
- [ ] Test developer identity initialization
- [ ] Test spec structure initialization
- [ ] Test task creation with PRD
- [ ] Test task context initialization
- [ ] Test worktree creation
- [ ] Test agent execution simulation
- [ ] Test task completion
- [ ] Test task archival
- [ ] Verify complete journal audit trail
- [ ] Verify final state snapshot

### Task 5.12: Integration Test Documentation
- [ ] Document test execution commands
- [ ] Document test fixtures and helpers
- [ ] Document test coverage requirements
- [ ] Add troubleshooting guide for test failures

---

## Phase 6: Superiority Features Beyond Trellis

### Phase 6A: High Priority Features

#### Task 6A.1: Advanced Event Sourcing & Time Travel
- [ ] Create `src/reins/kernel/event/time_travel.py`
- [ ] Implement `reconstruct_at(timestamp)` method
- [ ] Implement `query_tasks(timestamp)` method
- [ ] Create `src/reins/kernel/event/projections.py`
- [ ] Implement `agent_activity_summary()` projection
- [ ] Implement `task_timeline()` projection
- [ ] Add tests: `tests/unit/test_time_travel.py`
- [ ] Add integration test: `tests/integration/test_time_travel.py`

#### Task 6A.2: Policy-Driven Execution Engine
- [ ] Create `src/reins/policy/rules.py`
- [ ] Implement declarative policy rule parser
- [ ] Create `src/reins/policy/constraints.py`
- [ ] Implement runtime constraint enforcement
- [ ] Create `src/reins/policy/audit.py`
- [ ] Implement policy decision audit trail
- [ ] Create `.reins/policy.yaml` schema
- [ ] Add tests: `tests/unit/test_policy_rules.py`
- [ ] Add integration test: `tests/integration/test_policy_engine.py`

#### Task 6A.3: Context Compiler
- [ ] Create `src/reins/context/compiler.py`
- [ ] Implement multi-source context compilation
- [ ] Create `src/reins/context/optimizer.py`
- [ ] Implement token budget optimization
- [ ] Create `src/reins/context/cache.py`
- [ ] Implement context caching with TTL
- [ ] Add tests: `tests/unit/test_context_compiler.py`
- [ ] Add integration test: `tests/integration/test_context_compilation.py`

#### Task 6A.4: Approval Ledger
- [ ] Create `src/reins/approval/ledger.py`
- [ ] Implement approval request tracking
- [ ] Create `src/reins/approval/delegation.py`
- [ ] Implement approval delegation with expiry
- [ ] Create `src/reins/approval/audit.py`
- [ ] Implement approval audit trail
- [ ] Add tests: `tests/unit/test_approval_ledger.py`
- [ ] Add integration test: `tests/integration/test_approval_flow.py`

### Phase 6B: Medium Priority Features

#### Task 6B.1: MCP-Native Architecture
- [ ] Create `src/reins/mcp/session.py`
- [ ] Implement MCP session management
- [ ] Create `src/reins/mcp/registry.py`
- [ ] Implement tool/resource registry
- [ ] Create `src/reins/mcp/bridge.py`
- [ ] Implement bridge to external MCP servers
- [ ] Add tests: `tests/unit/test_mcp_session.py`
- [ ] Add integration test: `tests/integration/test_mcp_integration.py`

#### Task 6B.2: Enhanced Checkpoint/Resume System
- [ ] Enhance `src/reins/memory/checkpoint.py`
- [ ] Create `src/reins/memory/dehydration.py`
- [ ] Implement state dehydration
- [ ] Create `src/reins/memory/wake_conditions.py`
- [ ] Implement wake condition evaluation
- [ ] Support time-based, event-based, file-change wake conditions
- [ ] Add tests: `tests/unit/test_checkpoint_enhanced.py`
- [ ] Add integration test: `tests/integration/test_checkpoint_resume.py`

#### Task 6B.3: Evaluation Framework
- [ ] Create `src/reins/evaluation/metrics.py`
- [ ] Implement success metrics (coverage, lint, type errors)
- [ ] Create `src/reins/evaluation/feedback_loop.py`
- [ ] Implement learning from failures
- [ ] Create `src/reins/evaluation/quality_gates.py`
- [ ] Implement quality gate enforcement
- [ ] Add tests: `tests/unit/test_evaluation.py`
- [ ] Add integration test: `tests/integration/test_quality_gates.py`

#### Task 6B.4: Timeline Visualization
- [ ] Create `src/reins/observability/timeline.py`
- [ ] Implement timeline generation from events
- [ ] Create `src/reins/observability/visualization.py`
- [ ] Implement ASCII rendering
- [ ] Create `src/reins/observability/export.py`
- [ ] Implement JSON export for web UI
- [ ] Add tests: `tests/unit/test_timeline.py`
- [ ] Add CLI command: `reins timeline show`

### Phase 6C: Future Features

#### Task 6C.1: A2A Remote Agent Coordination
- [ ] Create `src/reins/a2a/protocol.py`
- [ ] Implement agent-to-agent protocol
- [ ] Create `src/reins/a2a/coordinator.py`
- [ ] Implement multi-agent coordination
- [ ] Create `src/reins/a2a/discovery.py`
- [ ] Implement agent discovery service
- [ ] Add tests: `tests/unit/test_a2a_protocol.py`
- [ ] Add integration test: `tests/integration/test_distributed_execution.py`

#### Task 6C.2: Skill Lazy Loading System
- [ ] Create `src/reins/skill/loader.py`
- [ ] Implement lazy skill loading
- [ ] Create `src/reins/skill/policy_envelope.py`
- [ ] Implement policy-wrapped skills
- [ ] Enhance `src/reins/skill/catalog.py`
- [ ] Add dynamic catalog updates
- [ ] Add tests: `tests/unit/test_skill_loader.py`
- [ ] Add integration test: `tests/integration/test_skill_execution.py`

### Task 6.13: Superiority Documentation
- [ ] Create comparison matrix: Trellis vs Reins
- [ ] Document all superiority features
- [ ] Create feature showcase examples
- [ ] Add performance benchmarks
- [ ] Create migration guide from Trellis to Reins

---

## Summary

**Phase 4 (CLI Commands):** 11 tasks, ~40 subtasks
**Phase 5 (Integration Tests):** 12 tasks, ~60 subtasks
**Phase 6 (Superiority Features):** 13 tasks, ~80 subtasks

**Total:** 36 tasks, ~180 subtasks

**Estimated Timeline:**
- Phase 4: 2-3 weeks
- Phase 5: 2-3 weeks
- Phase 6A: 3-4 weeks
- Phase 6B: 2-3 weeks
- Phase 6C: 3-4 weeks

**Total Estimated Time:** 12-17 weeks for complete implementation
