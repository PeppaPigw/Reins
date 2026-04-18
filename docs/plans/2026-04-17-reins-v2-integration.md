# Reins v2.0: Trellis-Inspired Native Capabilities

**Date:** 2026-04-17  
**Status:** Design Complete, Ready for Implementation  
**Goal:** Integrate trellis's best practices as native Reins capabilities

---

## Executive Summary

This document describes how Reins v2.0 absorbs three powerful patterns from trellis:

1. **Context Injection** - Project specs automatically injected into agent sessions
2. **Task Management** - Requirements, state, and progress tracked across sessions
3. **Worktree Parallelism** - Multiple agents working independently without conflicts

**Key principle:** Absorb the ideas, not the implementation. Make these first-class Reins capabilities, not external dependencies.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         REINS v2.0 ARCHITECTURE                     │
└─────────────────────────────────────────────────────────────────────┘

                            Event Journal
                                  │
                    ┌─────────────┼─────────────┐
                    │             │             │
                    ▼             ▼             ▼
            ContextSpec    TaskContext    WorktreeState
            Projection     Projection     Tracking
                    │             │             │
                    └─────────────┼─────────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    │             │             │
                    ▼             ▼             ▼
            ContextCompiler  TaskManager  WorktreeManager
                    │             │             │
                    └─────────────┼─────────────┘
                                  │
                                  ▼
                          Orchestrator.bootstrap_session()
                                  │
                    ┌─────────────┼─────────────┐
                    │             │             │
                    ▼             ▼             ▼
            Seed Context    Active Task    Subagent Spawn
            Injection       Tracking       (with worktree)
                    │             │             │
                    └─────────────┼─────────────┘
                                  │
                                  ▼
                          Agent Execution
```

---

## Component Integration

### 1. Context Injection System

**Purpose:** Automatically inject project conventions into agent sessions

**Components:**

- `SpecRegistrar` - Import specs from `.reins/spec/`, emit events
- `ContextSpecProjection` - Build queryable index from spec events
- `ContextCompiler` - Assemble context with token budget
- `ContextRecompositionManager` - Handle context updates on triggers

**Integration points:**

- **Orchestrator.bootstrap_session()** - Loads seed context at session start
- **TaskManager** - Provides active task for task contract injection
- **PolicyEngine** - Filters specs by granted capabilities
- **SubagentManager** - Inherits context to subagents

**Data flow:**

```
.reins/spec/*.yaml
    ↓
SpecRegistrar.import_from_directory()
    ↓
SpecRegisteredEvent → EventJournal
    ↓
ContextSpecProjection.apply_event()
    ↓
ContextSpecProjection.resolve(query)
    ↓
ContextCompiler.seed_context()
    ↓
ContextAssemblyManifest
    ↓
Orchestrator → Agent session
```

**Key features:**

- Event-sourced specs (immutable, auditable)
- Projection-based resolution (fast queries)
- Token-aware compilation (budget management)
- Per-turn enrichment (dynamic context)

---

### 2. Task Management System

**Purpose:** Track requirements, state, and progress across sessions

**Components:**

- `TaskMetadata` - Task identity, assignment, requirements
- `TaskContextProjection` - Project task events from journal
- `TaskManager` - Create, start, complete tasks
- `TaskContext` - Complete context for a task (PRD, events, decisions)

**Integration points:**

- **WorkflowGraph** - Tasks are workflow nodes with extended metadata
- **NodeStateTracker** - Tracks task status transitions
- **ContextCompiler** - Injects task PRD as task contract
- **Orchestrator** - Tracks active task in state

**Data flow:**

```
TaskManager.create_task(title, prd, ...)
    ↓
TaskCreatedEvent → EventJournal
    ↓
TaskContextProjection.apply_event()
    ↓
TaskManager.start_task(task_id)
    ↓
Orchestrator.set_active_task(task_id)
    ↓
ContextCompiler.seed_context(task_state)
    ↓
Task PRD injected as task contract
    ↓
Agent sees requirements in context
```

**Key features:**

- Tasks as workflow nodes (no parallel state system)
- Event-sourced task lifecycle (auditable)
- Task context from journal projection (single source of truth)
- Active task in orchestrator state (no file I/O)

---

### 3. Worktree Parallelism System

**Purpose:** Enable multiple agents to work independently without git conflicts

**Components:**

- `WorktreeConfig` - Configuration for worktree creation
- `WorktreeState` - Runtime state of a worktree
- `WorktreeManager` - Create, remove, merge worktrees
- `IsolationLevel` - Enum for subagent isolation (NONE, PROCESS, WORKTREE)

**Integration points:**

- **SubagentManager** - Spawns subagents with worktree isolation
- **TaskManager** - Provides task metadata for worktree naming
- **EventJournal** - Records worktree lifecycle events

**Data flow:**

```
SubagentManager.spawn_subagent(config)
    ↓
if isolation_level == WORKTREE:
    WorktreeManager.create_worktree(agent_id, task_id)
        ↓
        git worktree add ../reins-worktrees/{task_id}
        ↓
        Copy .reins/.developer, .reins/config.yaml
        ↓
        Run post-create hooks
        ↓
        WorktreeCreatedEvent → EventJournal
    ↓
Spawn agent in worktree directory
    ↓
Agent executes in isolated git state
    ↓
WorktreeManager.merge_worktree(worktree_id)
    ↓
git merge {branch} (in main repo)
    ↓
WorktreeManager.remove_worktree(worktree_id)
```

**Key features:**

- Worktree as isolation level (not separate system)
- Event-sourced worktree lifecycle (auditable)
- Automatic cleanup (idle detection)
- Parallel task execution (no git conflicts)

---

## End-to-End Scenarios

### Scenario 1: Single Task with Context Injection

**User action:** Create and execute a backend task

```python
# 1. Create task
task_id = task_manager.create_task(
    title="Implement JWT authentication",
    task_type="backend",
    prd_content="""
    ## Requirements
    - Use RS256 algorithm
    - Store tokens in Redis
    - 15-minute expiry
    """,
    acceptance_criteria=[
        "JWT tokens generated with RS256",
        "Tokens stored in Redis with TTL",
        "Token validation endpoint works"
    ],
    created_by="user"
)

# 2. Start task
task_manager.start_task(task_id, assignee="claude-agent")

# 3. Bootstrap session (automatic)
orchestrator.bootstrap_session()
    ↓
    # Load active task
    task_state = task_manager.get_active_task()

    # Assemble context
    manifest = context_compiler.seed_context(
        task_state=task_state,
        granted_capabilities={"fs:read", "fs:write"},
        token_budget=TokenBudget.default(10000)
    )

    # Manifest includes:
    # - Standing law: backend error handling, logging conventions
    # - Task contract: JWT authentication requirements
    # - Total tokens: ~3000

# 4. Agent executes with context
agent.execute(manifest)
    ↓
    # Agent sees:
    # - Project conventions (error handling, logging)
    # - Task requirements (RS256, Redis, 15-min expiry)
    # - Writes code following conventions

# 5. Complete task
task_manager.complete_task(task_id, outcome={"files_modified": 5})
```

**Result:** Agent writes code following project conventions without external hooks.

---

### Scenario 2: Parallel Tasks with Worktrees

**User action:** Execute 3 tasks in parallel

```python
# 1. Create tasks
task_ids = [
    task_manager.create_task("Implement user login", task_type="backend", ...),
    task_manager.create_task("Implement user registration", task_type="backend", ...),
    task_manager.create_task("Implement password reset", task_type="backend", ...)
]

# 2. Execute in parallel
executor = ParallelTaskExecutor(task_manager, subagent_manager, worktree_manager)
agent_ids = executor.execute_tasks_parallel(task_ids, agent_type="implement")

# Behind the scenes:
# For each task:
#   1. Create worktree: ../reins-worktrees/{task_id}/
#   2. Create branch: feat/{task_slug}
#   3. Copy .reins/.developer
#   4. Spawn subagent in worktree
#   5. Agent executes in isolation

# 3. Wait for completion
statuses = executor.wait_for_completion(list(agent_ids.values()), timeout_seconds=3600)

# 4. Merge results
for task_id, agent_id in agent_ids.items():
    if statuses[agent_id] == SubagentStatus.COMPLETED:
        subagent_manager.merge_subagent_work(agent_id, target_branch="main")
```

**Result:** 3 agents work simultaneously without git conflicts, each in isolated worktree.

---

### Scenario 3: Context Re-composition on Phase Change

**User action:** Agent moves from implement phase to check phase

```python
# 1. Agent completes implementation
orchestrator.handle_command(
    capability="fs:write",
    args={"path": "src/auth.py", "content": "..."},
    run_phase="implement"
)

# 2. Phase changes to check
orchestrator.transition_phase("implement" -> "check")
    ↓
    # Trigger context re-composition
    recomposition_manager.on_run_phase_change(
        new_phase="check",
        actor_type="check-agent",
        path="src/auth.py"
    )
    ↓
    # Enrich context with check-specific specs
    manifest = context_compiler.enrich_context(
        base_manifest=seed_manifest,
        run_phase="check",
        actor_type="check-agent",
        path="src/auth.py",
        granted_capabilities={"fs:read"},
        token_budget=TokenBudget.default(10000)
    )

    # New manifest includes:
    # - Standing law: (unchanged)
    # - Task contract: (unchanged)
    # - Spec shards: pytest conventions, code review checklist
    # - Total tokens: ~5000

# 3. Check agent executes with enriched context
check_agent.execute(manifest)
    ↓
    # Agent sees:
    # - Original project conventions
    # - Task requirements
    # - Check-specific guidance (pytest, review checklist)
```

**Result:** Agent sees phase-specific guidance without manual context management.

---

## Migration Path from Trellis

### Phase 1: Foundation (Weeks 1-4)

**Goal:** Implement core components without breaking existing trellis workflow

**Tasks:**

1. Implement SpecRegistrar and events
2. Implement ContextSpecProjection
3. Implement ContextCompiler
4. Implement TaskManager and events
5. Implement WorktreeManager

**Deliverables:**

- Can import specs from `.reins/spec/`
- Can create tasks via TaskManager
- Can create worktrees via WorktreeManager
- All operations event-sourced and auditable

**Trellis status:** Still active, no changes

---

### Phase 2: Integration (Weeks 5-8)

**Goal:** Integrate components with orchestrator

**Tasks:**

1. Add context injection to bootstrap_session()
2. Add active task tracking to orchestrator state
3. Add worktree isolation to SubagentManager
4. Implement checkpoint/hydrate for new state

**Deliverables:**

- Session bootstrap loads seed context
- Active task tracked in orchestrator
- Subagents can spawn in worktrees
- Checkpoint includes new state

**Trellis status:** Parallel operation begins

---

### Phase 3: Migration (Weeks 9-12)

**Goal:** Migrate existing workflows to Reins native

**Tasks:**

1. Import trellis specs to `.reins/spec/`
2. Import trellis tasks to Reins TaskManager
3. Update workflows to use Reins APIs
4. Test parallel operation

**Deliverables:**

- All specs in Reins
- All active tasks in Reins
- Workflows use both systems
- No regressions

**Trellis status:** Deprecated, but still functional

---

### Phase 4: Cleanup (Weeks 13-16)

**Goal:** Remove trellis dependencies

**Tasks:**

1. Remove trellis hooks
2. Archive `.trellis/` directory
3. Update documentation
4. Remove trellis scripts

**Deliverables:**

- Trellis completely removed
- Documentation updated
- Clean codebase

**Trellis status:** Removed

---

## Performance Considerations

### Context Injection

**Hot paths:**

- `resolve()` queries in-memory indexes: O(1) per index
- Token allocation: O(n) where n = matching specs (typically <20)
- Manifest assembly: O(n) serialization

**Cold paths:**

- Projection rebuild from journal: O(events) on startup
- Spec registration: O(1) event append

**Optimizations:**

- Cache manifests per (run_phase, actor_type, path)
- Lazy load spec content (store only metadata in projection)
- Compress spec content in journal

---

### Task Management

**Hot paths:**

- Get active task: O(1) orchestrator state access
- List tasks: O(n) where n = total tasks
- Get task context: O(1) projection dict access

**Cold paths:**

- Create task: O(1) event append + O(1) workflow node creation
- Projection rebuild: O(events) on startup

**Optimizations:**

- Add indexes (by_status, by_assignee, by_priority)
- Paginate task lists
- Cache task contexts

---

### Worktree Parallelism

**Hot paths:**

- Spawn subagent (no worktree): O(1) process spawn
- Check subagent status: O(1) dict lookup

**Cold paths:**

- Create worktree: O(repo_size) git operation + file copy
- Remove worktree: O(1) git operation
- Merge worktree: O(commits) git operation

**Optimizations:**

- Limit max concurrent worktrees (e.g., 10)
- Reuse worktrees for same task
- Use shallow clones (future)
- Use sparse checkouts (future)

---

## Testing Strategy

### Unit Tests

**Context Injection:**

- SpecRegistrar validation
- ContextSpecProjection event handling
- ContextCompiler token allocation
- Precedence sorting

**Task Management:**

- TaskManager lifecycle
- TaskContextProjection event handling
- Task dependencies
- Subtask creation

**Worktree Parallelism:**

- WorktreeManager create/remove
- Worktree state tracking
- Cleanup automation
- Orphan detection

---

### Integration Tests

**End-to-end scenarios:**

1. Create task → bootstrap session → context injected
2. Parallel tasks → worktrees created → agents execute → merge
3. Phase change → context re-composition → enriched context
4. Checkpoint → hydrate → state restored
5. Crash → recovery → orphaned worktrees cleaned

---

### Performance Tests

**Benchmarks:**

- Context resolution: <10ms for 100 specs
- Task list: <50ms for 1000 tasks
- Worktree creation: <5s for typical repo
- Parallel execution: 10 agents without degradation

---

## Security Considerations

### Context Injection

**Threats:**

- Malicious specs injected by untrusted source
- Model output becoming canonical spec
- Spec granting capabilities implicitly

**Mitigations:**

- Trust verification: only system/admin can register specs
- Staging area: model output goes to `.reins/drafts/`
- Clear separation: specs describe, policy grants

---

### Task Management

**Threats:**

- Unauthorized task creation
- Task PRD tampering
- Task state manipulation

**Mitigations:**

- Event-sourced: all changes auditable
- Provenance tracking: created_by, last_modified_by
- Immutable events: cannot modify history

---

### Worktree Parallelism

**Threats:**

- Worktree escape: agent accesses main repo
- Worktree pollution: malicious files in worktree
- Merge conflicts: corrupted merge

**Mitigations:**

- Sandboxed execution: agent restricted to worktree directory
- Verification hooks: check worktree before merge
- Manual merge review: human approves merge (v1)

---

## Open Questions

### Context Injection

1. Should specs support templating (e.g., `{{task_type}}` placeholders)?
2. Should specs support includes (e.g., `!include common.yaml`)?
3. Should specs support versioning beyond supersede?
4. Should specs support conditional inclusion (e.g., `if: task_type == backend`)?

### Task Management

1. Should tasks support custom fields (e.g., `estimated_hours`)?
2. Should tasks support labels/tags for filtering?
3. Should tasks support attachments (e.g., design mockups)?
4. Should tasks support comments/discussion?

### Worktree Parallelism

1. Should worktrees be reused for same task?
2. Should worktrees support snapshots for rollback?
3. Should worktrees support remote execution (SSH)?
4. Should worktrees support container isolation (Docker)?

---

## Success Metrics

### V1 Success Criteria

**Context Injection:**

- [ ] Specs imported from `.reins/spec/`
- [ ] Seed context assembled at session bootstrap
- [ ] Agent sees project conventions
- [ ] All operations auditable

**Task Management:**

- [ ] Tasks created with PRD
- [ ] Active task tracked in orchestrator
- [ ] Task PRD injected as task contract
- [ ] All operations auditable

**Worktree Parallelism:**

- [ ] Worktrees created for subagents
- [ ] Multiple agents execute in parallel
- [ ] Worktrees cleaned up after completion
- [ ] All operations auditable

---

### V2 Success Criteria

**Context Injection:**

- [ ] Per-turn enrichment working
- [ ] Capability filtering working
- [ ] Conflict resolution working
- [ ] Fast/deliberative paths optimized

**Task Management:**

- [ ] Subtasks and dependencies working
- [ ] Task archival working
- [ ] Git branch integration working
- [ ] Advanced queries working

**Worktree Parallelism:**

- [ ] Merge automation working
- [ ] Worktree snapshot/restore working
- [ ] Shallow clones working
- [ ] Grant inheritance in worktrees working

---

## Next Steps

1. **Review designs** - Team review of all three design documents
2. **Prioritize phases** - Decide implementation order
3. **Create tasks** - Break down into implementable tasks
4. **Start Phase 1** - Begin with SpecRegistrar + events
5. **Iterate** - Build, test, refine, repeat

---

## Conclusion

Reins v2.0 absorbs trellis's best practices as native capabilities:

- **Context injection** ensures agents follow project conventions
- **Task management** tracks requirements and progress across sessions
- **Worktree parallelism** enables multiple agents to work independently

These are not bolted-on features, but first-class Reins primitives:

- Event-sourced (immutable, auditable)
- Projection-based (fast queries)
- Orchestrator-integrated (coherent system)
- Checkpoint-friendly (survives restarts)

The result: **Reins surpasses trellis** by making these patterns native, not external.
