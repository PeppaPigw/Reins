# Phase 5: Integration Tests for End-to-End Workflows

## Overview

Create integration tests that verify complete workflows through the Reins kernel. Tests should cover happy paths, failure scenarios, and edge cases.

## Test Breakdown

### 1. Task Lifecycle Integration Test

**File:** `tests/integration/test_task_lifecycle.py`

**Workflow:**
1. Create task with CLI command
2. Verify task directory structure created
3. Verify `task.created` event in journal
4. Start task (set `.current-task`)
5. Verify `task.started` event
6. Add context files (implement.jsonl, check.jsonl)
7. Finish task (clear `.current-task`)
8. Verify `task.finished` event
9. Archive task
10. Verify `task.archived` event

**Assertions:**
- Task JSON matches input
- Events contain correct payload
- File system state matches expected
- Current task pointer updates correctly

### 2. Spec Injection Integration Test

**File:** `tests/integration/test_spec_injection.py`

**Workflow:**
1. Initialize spec structure for package
2. Create task with package assignment
3. Initialize context with `init-context` command
4. Verify default spec files added to JSONL
5. Add custom spec file with `add-context`
6. Verify JSONL contains all expected entries
7. Simulate hook reading JSONL
8. Verify hook output contains spec content

**Assertions:**
- Spec files created with correct structure
- JSONL format is valid
- Hook can parse and inject content
- Context includes Pre-Development Checklist

### 3. Worktree Parallel Execution Test

**File:** `tests/integration/test_worktree_parallel.py`

**Workflow:**
1. Create 3 tasks
2. Create worktree for each task in parallel
3. Verify each worktree has:
   - Separate git branch
   - Copied `.developer` file
   - Task pointer set to correct task
   - Agent registered in registry
4. Verify post-create hooks ran
5. Verify verification hooks passed
6. Cleanup all worktrees
7. Verify agents unregistered

**Assertions:**
- Worktrees are isolated (separate git state)
- Registry tracks all active agents
- Cleanup removes worktrees and unregisters agents
- No orphaned worktrees remain

### 4. Migration System Integration Test

**File:** `tests/integration/test_migration_system.py`

**Workflow:**
1. Create test repo with old structure
2. Create migration manifest (0.1.0)
3. Run migration with dry-run
4. Verify dry-run shows expected operations
5. Run migration for real
6. Verify files moved/deleted correctly
7. Verify migration events in journal
8. Run migration again (idempotency test)
9. Verify operations skipped
10. Test rollback on failure

**Assertions:**
- Migrations are idempotent
- Rollback restores original state
- Events track all operations
- Safe-file-delete protects modified files

### 5. Event Sourcing Integration Test

**File:** `tests/integration/test_event_sourcing.py`

**Workflow:**
1. Perform sequence of operations:
   - Create task
   - Start task
   - Create worktree
   - Register agent
   - Run migration
   - Finish task
2. Read journal and verify event sequence
3. Replay events to reconstruct state
4. Verify reconstructed state matches current state
5. Test state reduction from events

**Assertions:**
- All operations emit events
- Events are ordered correctly
- Replay produces correct state
- Reducer is pure (no side effects)

### 6. Multi-Agent Coordination Test

**File:** `tests/integration/test_multi_agent.py`

**Workflow:**
1. Create parent task with 3 subtasks
2. Create worktree for each subtask
3. Simulate agents working in parallel:
   - Each agent reads its task context
   - Each agent writes to its worktree
   - Each agent sends heartbeats
4. Verify agents don't interfere with each other
5. Verify registry tracks all agents
6. Simulate one agent failing
7. Verify cleanup handles partial failure
8. Verify other agents continue working

**Assertions:**
- Agents are isolated (no cross-contamination)
- Registry heartbeats update correctly
- Partial failure doesn't affect other agents
- Cleanup is safe (no data loss)

### 7. Policy Engine Integration Test

**File:** `tests/integration/test_policy_engine.py`

**Workflow:**
1. Create command proposals with different risk tiers
2. Verify policy engine evaluates correctly
3. Test grant issuance for approved commands
4. Test rejection for high-risk commands
5. Verify policy decisions logged to journal
6. Test capability taxonomy lookup

**Assertions:**
- Risk tiers assigned correctly
- Grants contain correct capabilities
- Rejections include reason
- Policy decisions are auditable

### 8. Checkpoint/Resume Integration Test

**File:** `tests/integration/test_checkpoint_resume.py`

**Workflow:**
1. Start long-running task
2. Create checkpoint mid-execution
3. Verify checkpoint manifest saved
4. Simulate process interruption
5. Resume from checkpoint
6. Verify state restored correctly
7. Verify work continues from checkpoint

**Assertions:**
- Checkpoint captures complete state
- Resume restores all context
- No duplicate work after resume
- Events track checkpoint/resume

### 9. Error Handling Integration Test

**File:** `tests/integration/test_error_handling.py`

**Workflow:**
1. Test missing file scenarios
2. Test invalid JSON in task files
3. Test corrupted journal
4. Test git worktree failures
5. Test migration rollback on error
6. Test agent registration conflicts
7. Verify error events in journal
8. Verify system remains consistent

**Assertions:**
- Errors don't corrupt state
- Error messages are actionable
- Partial operations roll back
- Journal remains valid

### 10. Full Workflow Integration Test

**File:** `tests/integration/test_full_workflow.py`

**Workflow:**
1. Initialize developer identity
2. Initialize spec structure
3. Create task with PRD
4. Initialize task context
5. Create worktree for task
6. Simulate agent execution:
   - Read context from JSONL
   - Execute commands via adapters
   - Write results
7. Verify task completion
8. Archive task
9. Verify journal contains complete audit trail
10. Verify state snapshot matches expected

**Assertions:**
- Complete workflow executes without errors
- All events logged correctly
- State is consistent throughout
- Cleanup leaves no artifacts

## Test Infrastructure

### Fixtures

**File:** `tests/integration/conftest.py`

```python
@pytest.fixture
def temp_repo(tmp_path):
    """Create temporary git repo with Reins initialized."""
    repo = tmp_path / "test-repo"
    repo.mkdir()
    # Initialize git
    subprocess.run(["git", "init"], cwd=repo)
    # Initialize Reins structure
    (repo / ".reins").mkdir()
    (repo / ".reins" / "spec").mkdir()
    (repo / ".reins" / "tasks").mkdir()
    (repo / ".reins" / "workspace").mkdir()
    # Create journal
    journal = EventJournal(repo / ".reins" / "journal.jsonl")
    return repo, journal

@pytest.fixture
def mock_adapter():
    """Mock adapter for testing without real execution."""
    return MockAdapter()

@pytest.fixture
def test_config():
    """Standard test configuration."""
    return {
        "worktree_dir": "../test-worktrees",
        "copy": [".reins/.developer"],
        "post_create": ["echo 'setup'"],
        "verify": ["test -f .reins/.developer"],
    }
```

### Helpers

**File:** `tests/integration/helpers.py`

```python
def wait_for_event(journal: EventJournal, event_type: str, timeout: int = 5):
    """Wait for specific event to appear in journal."""
    
def verify_journal_sequence(journal: EventJournal, expected_types: list[str]):
    """Verify events appear in expected order."""
    
def create_test_task(repo_root: Path, title: str) -> str:
    """Create task for testing."""
    
def simulate_agent_work(worktree_path: Path, duration: float):
    """Simulate agent working in worktree."""
```

## Test Execution

### Run all integration tests:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/integration -q
```

### Run specific workflow:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/integration/test_full_workflow.py -q
```

### Run with coverage:
```bash
python -m coverage erase
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m coverage run \
  --source=src/reins/task,src/reins/isolation,src/reins/kernel,src/reins/memory,src/reins/policy,src/reins/migration \
  -m pytest tests/integration -q
python -m coverage report -m
```

### Troubleshooting

- `pytest --cov ...` fails with `unrecognized arguments`
  This repo does not currently install `pytest-cov`; use `coverage.py` directly.

- Worktree creation fails before the first test runs
  Ensure the temporary repo sets `git config user.name` and `git config user.email` before committing.

- Orphan worktree cleanup tests fail because the branch is already checked out
  Create the synthetic orphan from detached `HEAD` rather than checking out the main branch twice.

- Idle worktree cleanup does not remove synthetic worktrees
  Copied `.reins/` and `.trellis/` metadata can create untracked content that blocks non-force removal; remove that copied metadata before exercising the idle cleanup path.

- Full workflow resume loses open shell handles
  The shell adapter handle kinds must match the dispatcher freeze/thaw registry names (`shell_sandboxed`, `shell_network`).

- Task context is missing inside a child worktree
  Agent worktree creation must copy `.reins/tasks/<task_id>` into the new worktree before writing `.current-task`.

## Success Criteria

- [ ] All 10 integration test suites implemented
- [ ] Tests cover happy paths and failure scenarios
- [ ] Tests verify event sourcing correctness
- [ ] Tests verify state consistency
- [ ] Tests verify isolation between agents
- [ ] Tests verify rollback behavior
- [ ] Tests run in CI/CD pipeline
- [ ] Coverage > 85% for integration paths
- [ ] Tests complete in < 60 seconds total
- [ ] No flaky tests (run 10x without failure)
