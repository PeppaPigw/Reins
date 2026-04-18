# Worktree Patterns for Parallel Agent Execution

## Overview

Reins uses git worktrees to enable true parallel agent execution. Multiple agents can work on separate isolated worktrees simultaneously without blocking each other or causing merge conflicts during development.

## Core Components

### 1. WorktreeManager (`src/reins/isolation/worktree_manager.py`)

Central lifecycle manager for all worktree operations. Emits events to the journal for audit trail.

**Key Methods:**

```python
# High-level agent-oriented API (new in Phase 3)
async def create_worktree_for_agent(
    self,
    agent_id: str,
    task_id: str | None,
    branch_name: str,
    base_branch: str,
    config_path: Path | None = None,
) -> WorktreeState

async def verify_worktree(self, worktree_id: str) -> None

async def cleanup_agent_worktree(
    self,
    worktree_id: str,
    force: bool = False,
    removed_by: str = "system",
) -> None

# Low-level API (backward compatible)
async def create_worktree(
    self,
    agent_id: str,
    task_id: str | None,
    config: WorktreeConfig,
) -> WorktreeState
```

### 2. Worktree Configuration (`src/reins/isolation/worktree_config.py`)

YAML-based configuration system for declarative worktree setup.

**Configuration Lookup Priority:**
1. Explicit `config_path` parameter
2. `.reins/worktree.yaml`
3. `.trellis/worktree.yaml`
4. Built-in defaults

**Example Configuration:**

```yaml
# .reins/worktree.yaml
worktree_dir: ../reins-worktrees
copy:
  - .reins/.developer
  - .reins/.current-task
post_create:
  - python -V
  - pip install -e .
verify:
  - test -f .reins/.developer
  - python -c "import reins"
```

**Configuration Model:**

```python
@dataclass(frozen=True)
class WorktreeTemplateConfig:
    worktree_dir: Path              # Base directory for worktrees
    copy: list[str]                 # Files to copy from main repo
    post_create: list[str]          # Commands to run after creation
    verify: list[str]               # Commands to verify setup
    source_path: Path | None        # Path to YAML file
```

### 3. Agent Registry (`src/reins/isolation/agent_registry.py`)

Persistent tracking of active agents with JSON-based storage.

**Registry Model:**

```python
@dataclass(frozen=True)
class AgentRegistryRecord:
    agent_id: str
    worktree_id: str
    task_id: str | None
    status: str                     # "starting", "running", "idle", "stopping"
    started_at: datetime
    last_heartbeat: datetime
```

**Key Operations:**

```python
# Register new agent
await registry.register(
    agent_id="agent-123",
    worktree_id="wt-456",
    task_id="task-789",
    status="starting",
)

# Update heartbeat
await registry.heartbeat(
    agent_id="agent-123",
    status="running",
)

# Unregister agent
await registry.unregister(agent_id="agent-123")

# Query agents
active_agents = registry.list_active()
agent_record = registry.get(agent_id="agent-123")
task_agents = registry.find_by_task(task_id="task-789")
```

## Usage Patterns

### Pattern 1: Create Agent Worktree

```python
from pathlib import Path
from reins.isolation import WorktreeManager
from reins.kernel.event.journal import EventJournal

# Initialize manager
journal = EventJournal(Path(".reins/journal.jsonl"))
manager = WorktreeManager(
    journal=journal,
    run_id="run-123",
    repo_root=Path.cwd(),
)

# Create worktree for agent
state = await manager.create_worktree_for_agent(
    agent_id="agent-123",
    task_id="task-789",
    branch_name="feat/task-789",
    base_branch="main",
)

# Worktree is now ready at state.worktree_path
# Agent is registered in registry.json
# Identity files are copied
# Task pointers are set (.reins/.current-task, .trellis/.current-task)
```

### Pattern 2: Verify Worktree Setup

```python
# Run verification hooks from worktree.yaml
try:
    await manager.verify_worktree(state.worktree_id)
    print("Worktree verified successfully")
except WorktreeError as e:
    print(f"Verification failed: {e}")
    await manager.cleanup_agent_worktree(state.worktree_id, force=True)
```

### Pattern 3: Clean Up After Agent Completes

```python
# Clean up worktree and unregister agent
await manager.cleanup_agent_worktree(
    worktree_id=state.worktree_id,
    force=False,  # Don't discard uncommitted changes
    removed_by="orchestrator",
)

# If agent failed and you want to discard changes:
await manager.cleanup_agent_worktree(
    worktree_id=state.worktree_id,
    force=True,  # Discard all changes
    removed_by="orchestrator",
)
```

### Pattern 4: Parallel Agent Execution

```python
# Launch multiple agents in parallel
agents = []
for i in range(3):
    state = await manager.create_worktree_for_agent(
        agent_id=f"agent-{i}",
        task_id=f"task-{i}",
        branch_name=f"feat/task-{i}",
        base_branch="main",
    )
    agents.append(state)

# Each agent works in isolation
# No git conflicts during development
# Each has its own .reins/.current-task pointer
```

### Pattern 5: Monitor Active Agents

```python
from reins.isolation import AgentRegistry

registry = AgentRegistry(
    registry_path=Path(".reins/registry.json"),
    journal=journal,
    run_id="run-123",
)

# List all active agents
active = registry.list_active()
for record in active:
    print(f"Agent {record.agent_id}: {record.status}")
    print(f"  Worktree: {record.worktree_id}")
    print(f"  Task: {record.task_id}")
    print(f"  Last heartbeat: {record.last_heartbeat}")

# Find agents working on specific task
task_agents = registry.find_by_task("task-789")
```

## Event Sourcing

All worktree operations emit events to the journal:

**Worktree Events:**
- `worktree.created` - Worktree created with config
- `worktree.verified` - Verification hooks passed
- `worktree.removed` - Worktree removed
- `worktree.merged` - Changes merged back to main repo

**Agent Registry Events:**
- `agent.registered` - Agent registered with worktree
- `agent.heartbeat_updated` - Agent heartbeat updated
- `agent.unregistered` - Agent unregistered

**Event Example:**

```json
{
  "run_id": "run-123",
  "actor": "runtime",
  "type": "worktree.created",
  "payload": {
    "worktree_id": "agent-123-20260418-143022",
    "worktree_path": "/path/to/reins-worktrees/task-789",
    "branch_name": "feat/task-789",
    "base_branch": "main",
    "agent_id": "agent-123",
    "task_id": "task-789",
    "created_at": "2026-04-18T14:30:22Z",
    "config": {
      "copy_files": [".reins/.developer"],
      "post_create_commands": ["python -V"],
      "cleanup_on_success": true
    }
  }
}
```

## Error Handling

### Partial Failure Cleanup

If worktree creation succeeds but post-create setup fails, the manager automatically:
1. Force-removes the partial worktree
2. Unregisters the agent (if registered)
3. Surfaces the original error

This prevents orphaned worktrees.

### Orphan Detection

```python
# Detect worktrees that exist in git but aren't tracked
orphans = manager.detect_orphans()
for orphan_path in orphans:
    print(f"Orphaned worktree: {orphan_path}")

# Clean up orphans
cleaned = await manager.cleanup_orphans(force=True)
```

### Idle Cleanup

```python
# Clean up worktrees idle for more than 1 hour
cleaned_ids = await manager.cleanup_idle(idle_threshold_seconds=3600)
```

## Integration with Subagent Manager

The `SubagentManager` (`src/reins/subagent/manager.py`) integrates with worktree system:

```python
# SubagentManager automatically uses cleanup_agent_worktree()
# when worktree isolation is enabled
async def cleanup_worktree(self, worktree_id: str) -> None:
    if self._worktree_manager:
        await self._worktree_manager.cleanup_agent_worktree(
            worktree_id=worktree_id,
            force=False,
            removed_by="subagent_manager",
        )
```

## Best Practices

### 1. Always Use High-Level API

Prefer `create_worktree_for_agent()` over `create_worktree()`:
- Loads configuration from YAML
- Copies identity files automatically
- Sets task pointers
- Registers agent
- Handles partial failures

### 2. Set Task Pointers

The manager automatically writes:
- `.reins/.current-task` - Points to task directory
- `.trellis/.current-task` - Backward compatibility

This enables hooks to inject task context automatically.

### 3. Use Verification Hooks

Define `verify` commands in `worktree.yaml` to catch setup issues early:

```yaml
verify:
  - test -f .reins/.developer
  - python -c "import reins"
  - git status
```

### 4. Handle Cleanup Properly

Always clean up worktrees when agents complete:
- Use `force=False` to preserve uncommitted work
- Use `force=True` only when discarding failed work
- Let the manager handle unregistration

### 5. Monitor Agent Health

Use heartbeat updates to track agent liveness:

```python
# Agent should send heartbeats periodically
await registry.heartbeat(
    agent_id="agent-123",
    status="running",
)

# Orchestrator can detect stale agents
for record in registry.list_active():
    age = datetime.now(UTC) - record.last_heartbeat
    if age.total_seconds() > 300:  # 5 minutes
        print(f"Agent {record.agent_id} may be stale")
```

## Anti-Patterns

### ❌ Don't Create Worktrees Manually

```python
# BAD: Manual git worktree add
subprocess.run(["git", "worktree", "add", path, branch])

# GOOD: Use WorktreeManager
await manager.create_worktree_for_agent(...)
```

### ❌ Don't Skip Cleanup

```python
# BAD: Leave worktrees around
# (causes disk bloat and orphaned branches)

# GOOD: Always clean up
try:
    # ... agent work ...
finally:
    await manager.cleanup_agent_worktree(worktree_id)
```

### ❌ Don't Ignore Verification Failures

```python
# BAD: Proceed even if verification fails
try:
    await manager.verify_worktree(worktree_id)
except WorktreeError:
    pass  # Ignore and continue

# GOOD: Handle verification failures
try:
    await manager.verify_worktree(worktree_id)
except WorktreeError as e:
    await manager.cleanup_agent_worktree(worktree_id, force=True)
    raise
```

### ❌ Don't Modify Registry Directly

```python
# BAD: Edit registry.json manually
with open(".reins/registry.json", "w") as f:
    json.dump(data, f)

# GOOD: Use AgentRegistry API
await registry.register(...)
await registry.unregister(...)
```

## Testing

See test files for examples:
- `tests/unit/test_worktree_config.py` - Configuration loading
- `tests/unit/test_agent_registry.py` - Registry operations
- `tests/unit/test_worktree_manager_unit.py` - Manager unit tests
- `tests/integration/test_worktree_manager_parallel.py` - Parallel execution
- `tests/integration/test_subagent_worktree.py` - Subagent integration

## References

- [Trellis Worktree System](../../memo/Fromtrellis.md#part-4-worktree-based-parallel-execution)
- [Phase 3 Documentation](../../docs/PHASE3-COMPLETE.md)
- [WorktreeManager Source](../../src/reins/isolation/worktree_manager.py)
- [Agent Registry Source](../../src/reins/isolation/agent_registry.py)
