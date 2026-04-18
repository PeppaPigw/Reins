# Worktree Parallelism System - Reins Native Design

**Date:** 2026-04-17  
**Status:** Design Complete, Ready for Implementation  
**Goal:** Absorb trellis's worktree parallelism as native Reins subagent orchestration

---

## A. Architectural Conclusion

**Is this direction stable?** YES.

Trellis's worktree parallelism solves: **multiple agents working on different tasks without git conflicts**.

Reins already has:

- **SubagentManager** - spawns and coordinates agents
- **Grant inheritance** - secure permission delegation
- **Execution boundaries** - sandboxed adapters

**Key insight:** Worktrees are an **isolation primitive**, not a workflow primitive. Map them to Reins's existing isolation model.

**Design principle:** Worktree management is a **subagent spawn strategy**, not a separate system.

---

## B. Core Design

### 1. Isolation Levels

Reins supports multiple isolation levels for subagent execution:

```python
class IsolationLevel(str, Enum):
    """Isolation level for subagent execution."""
    NONE = "none"  # Same process, shared state
    PROCESS = "process"  # Separate process, shared filesystem
    WORKTREE = "worktree"  # Separate git worktree, isolated filesystem
    CONTAINER = "container"  # Docker container (future)
    REMOTE = "remote"  # Remote machine via A2A (future)

@dataclass
class SubagentConfig:
    """Configuration for subagent spawn."""
    agent_id: str
    agent_type: str  # "implement" | "check" | "debug" | "research"

    # Isolation
    isolation_level: IsolationLevel
    worktree_config: WorktreeConfig | None  # Only if isolation_level == WORKTREE

    # Task assignment
    task_id: str | None
    node_id: str | None

    # Grant inheritance
    inherited_grants: list[str]
    capability_restrictions: set[str]  # Capabilities NOT inherited

    # Context
    context_manifest: ContextAssemblyManifest | None

    # Lifecycle
    timeout_seconds: int
    auto_cleanup: bool
```

---

### 2. Worktree Configuration

```python
@dataclass
class WorktreeConfig:
    """Configuration for git worktree creation."""
    # Location
    worktree_base_dir: Path  # e.g., ../reins-worktrees
    worktree_name: str  # e.g., "04-17-auth-feature"

    # Git
    branch_name: str  # e.g., "feat/auth-feature"
    base_branch: str  # e.g., "main"
    create_branch: bool  # True = create new branch, False = use existing

    # Files to copy from main repo
    copy_files: list[str]  # e.g., [".reins/.developer", ".reins/config.yaml"]

    # Post-creation hooks
    post_create_commands: list[str]  # e.g., ["pip install -e .", "pytest --collect-only"]

    # Verification
    verify_commands: list[str]  # e.g., ["ruff check", "mypy src/"]

    # Cleanup
    cleanup_on_success: bool  # True = remove worktree after success
    cleanup_on_failure: bool  # False = keep worktree for debugging

@dataclass
class WorktreeState:
    """Runtime state of a worktree."""
    worktree_id: str  # ULID
    worktree_path: Path
    branch_name: str
    agent_id: str  # Which agent is using this worktree
    task_id: str | None

    # Status
    status: WorktreeStatus
    created_at: datetime
    last_active_at: datetime

    # Git state
    commit_count: int  # Commits made in this worktree
    has_uncommitted_changes: bool

    # Cleanup
    marked_for_cleanup: bool
    cleanup_reason: str | None

class WorktreeStatus(str, Enum):
    CREATING = "creating"
    ACTIVE = "active"
    IDLE = "idle"
    MERGING = "merging"
    CLEANING_UP = "cleaning_up"
    REMOVED = "removed"
```

---

### 3. Worktree Manager

```python
class WorktreeManager:
    """Manages git worktree lifecycle for parallel agent execution."""

    def __init__(
        self,
        repo_root: Path,
        journal: EventJournal,
        config: WorktreeConfig
    ):
        self.repo_root = repo_root
        self.journal = journal
        self.config = config
        self.worktrees: dict[str, WorktreeState] = {}

    def create_worktree(
        self,
        agent_id: str,
        task_id: str | None,
        config: WorktreeConfig
    ) -> WorktreeState:
        """
        Create a new git worktree for agent execution.

        Steps:
        1. Generate worktree ID and path
        2. Create git worktree with branch
        3. Copy required files from main repo
        4. Run post-create hooks
        5. Verify worktree is ready
        6. Emit WorktreeCreatedEvent
        7. Return WorktreeState
        """
        worktree_id = generate_ulid()
        worktree_path = config.worktree_base_dir / config.worktree_name

        # Ensure base directory exists
        config.worktree_base_dir.mkdir(parents=True, exist_ok=True)

        # Create git worktree
        if config.create_branch:
            # Create new branch from base_branch
            subprocess.run(
                [
                    "git", "worktree", "add",
                    str(worktree_path),
                    "-b", config.branch_name,
                    config.base_branch
                ],
                cwd=self.repo_root,
                check=True,
                capture_output=True
            )
        else:
            # Use existing branch
            subprocess.run(
                [
                    "git", "worktree", "add",
                    str(worktree_path),
                    config.branch_name
                ],
                cwd=self.repo_root,
                check=True,
                capture_output=True
            )

        # Copy files
        for file_path in config.copy_files:
            src = self.repo_root / file_path
            dst = worktree_path / file_path
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

        # Run post-create hooks
        for cmd in config.post_create_commands:
            subprocess.run(
                cmd,
                shell=True,
                cwd=worktree_path,
                check=True,
                capture_output=True
            )

        # Verify
        for cmd in config.verify_commands:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=worktree_path,
                capture_output=True
            )
            if result.returncode != 0:
                # Cleanup and raise
                self._cleanup_worktree(worktree_path)
                raise RuntimeError(f"Worktree verification failed: {cmd}")

        # Create state
        state = WorktreeState(
            worktree_id=worktree_id,
            worktree_path=worktree_path,
            branch_name=config.branch_name,
            agent_id=agent_id,
            task_id=task_id,
            status=WorktreeStatus.ACTIVE,
            created_at=datetime.now(UTC),
            last_active_at=datetime.now(UTC),
            commit_count=0,
            has_uncommitted_changes=False,
            marked_for_cleanup=False,
            cleanup_reason=None
        )
        self.worktrees[worktree_id] = state

        # Emit event
        event = WorktreeCreatedEvent(
            worktree_id=worktree_id,
            worktree_path=str(worktree_path),
            branch_name=config.branch_name,
            agent_id=agent_id,
            task_id=task_id,
            timestamp=datetime.now(UTC)
        )
        self.journal.append(event)

        return state

    def remove_worktree(
        self,
        worktree_id: str,
        force: bool = False
    ) -> None:
        """
        Remove a git worktree.

        Args:
            worktree_id: ID of worktree to remove
            force: If True, remove even with uncommitted changes
        """
        state = self.worktrees.get(worktree_id)
        if not state:
            raise ValueError(f"Worktree {worktree_id} not found")

        # Check for uncommitted changes
        if not force and state.has_uncommitted_changes:
            raise RuntimeError(
                f"Worktree {worktree_id} has uncommitted changes. "
                "Commit or use force=True to discard."
            )

        # Remove git worktree
        subprocess.run(
            ["git", "worktree", "remove", str(state.worktree_path), "--force" if force else ""],
            cwd=self.repo_root,
            check=True,
            capture_output=True
        )

        # Update state
        state.status = WorktreeStatus.REMOVED

        # Emit event
        event = WorktreeRemovedEvent(
            worktree_id=worktree_id,
            forced=force,
            timestamp=datetime.now(UTC)
        )
        self.journal.append(event)

    def merge_worktree(
        self,
        worktree_id: str,
        target_branch: str = "main",
        strategy: str = "merge"  # "merge" | "rebase" | "squash"
    ) -> None:
        """
        Merge worktree branch back to target branch.

        Steps:
        1. Verify worktree has no uncommitted changes
        2. Switch to target branch in main repo
        3. Merge/rebase worktree branch
        4. Push if configured
        5. Mark worktree for cleanup
        """
        state = self.worktrees.get(worktree_id)
        if not state:
            raise ValueError(f"Worktree {worktree_id} not found")

        if state.has_uncommitted_changes:
            raise RuntimeError(f"Worktree {worktree_id} has uncommitted changes")

        # Switch to target branch
        subprocess.run(
            ["git", "checkout", target_branch],
            cwd=self.repo_root,
            check=True
        )

        # Merge
        if strategy == "merge":
            subprocess.run(
                ["git", "merge", state.branch_name],
                cwd=self.repo_root,
                check=True
            )
        elif strategy == "rebase":
            subprocess.run(
                ["git", "rebase", state.branch_name],
                cwd=self.repo_root,
                check=True
            )
        elif strategy == "squash":
            subprocess.run(
                ["git", "merge", "--squash", state.branch_name],
                cwd=self.repo_root,
                check=True
            )

        # Update state
        state.status = WorktreeStatus.MERGING
        state.marked_for_cleanup = True
        state.cleanup_reason = "merged"

        # Emit event
        event = WorktreeMergedEvent(
            worktree_id=worktree_id,
            target_branch=target_branch,
            strategy=strategy,
            timestamp=datetime.now(UTC)
        )
        self.journal.append(event)

    def update_worktree_state(self, worktree_id: str) -> None:
        """Update worktree state by checking git status."""
        state = self.worktrees.get(worktree_id)
        if not state:
            return

        # Check for uncommitted changes
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=state.worktree_path,
            capture_output=True,
            text=True
        )
        state.has_uncommitted_changes = bool(result.stdout.strip())

        # Count commits
        result = subprocess.run(
            ["git", "rev-list", "--count", f"{self.config.base_branch}..HEAD"],
            cwd=state.worktree_path,
            capture_output=True,
            text=True
        )
        state.commit_count = int(result.stdout.strip())

        # Update last active
        state.last_active_at = datetime.now(UTC)

    def list_worktrees(self) -> list[WorktreeState]:
        """List all active worktrees."""
        return [
            state for state in self.worktrees.values()
            if state.status != WorktreeStatus.REMOVED
        ]

    def cleanup_idle_worktrees(self, idle_threshold_hours: int = 24) -> None:
        """Remove worktrees that have been idle for too long."""
        now = datetime.now(UTC)
        for state in self.worktrees.values():
            if state.status == WorktreeStatus.REMOVED:
                continue

            idle_hours = (now - state.last_active_at).total_seconds() / 3600
            if idle_hours > idle_threshold_hours:
                state.marked_for_cleanup = True
                state.cleanup_reason = f"idle for {idle_hours:.1f} hours"
                self.remove_worktree(state.worktree_id, force=False)
```

---

### 4. Integration with SubagentManager

```python
class SubagentManager:
    """Manages subagent lifecycle and coordination."""

    def __init__(
        self,
        journal: EventJournal,
        orchestrator: Orchestrator,
        worktree_manager: WorktreeManager
    ):
        self.journal = journal
        self.orchestrator = orchestrator
        self.worktree_manager = worktree_manager
        self.subagents: dict[str, SubagentState] = {}

    def spawn_subagent(
        self,
        config: SubagentConfig
    ) -> str:
        """
        Spawn a new subagent with specified isolation level.

        If isolation_level == WORKTREE:
        1. Create worktree via WorktreeManager
        2. Spawn agent in worktree directory
        3. Track worktree_id in SubagentState
        4. Agent executes in isolated git state
        """
        agent_id = generate_ulid()

        # Handle worktree isolation
        worktree_id = None
        working_directory = None

        if config.isolation_level == IsolationLevel.WORKTREE:
            if not config.worktree_config:
                raise ValueError("worktree_config required for WORKTREE isolation")

            # Create worktree
            worktree_state = self.worktree_manager.create_worktree(
                agent_id=agent_id,
                task_id=config.task_id,
                config=config.worktree_config
            )
            worktree_id = worktree_state.worktree_id
            working_directory = worktree_state.worktree_path

        # Create subagent state
        state = SubagentState(
            agent_id=agent_id,
            agent_type=config.agent_type,
            isolation_level=config.isolation_level,
            worktree_id=worktree_id,
            working_directory=working_directory,
            task_id=config.task_id,
            node_id=config.node_id,
            status=SubagentStatus.SPAWNING,
            spawned_at=datetime.now(UTC),
            inherited_grants=config.inherited_grants,
            capability_restrictions=config.capability_restrictions
        )
        self.subagents[agent_id] = state

        # Emit event
        event = SubagentSpawnedEvent(
            agent_id=agent_id,
            agent_type=config.agent_type,
            isolation_level=config.isolation_level,
            worktree_id=worktree_id,
            task_id=config.task_id,
            timestamp=datetime.now(UTC)
        )
        self.journal.append(event)

        # Start agent execution (async)
        self._start_agent_execution(agent_id, config)

        return agent_id

    def terminate_subagent(
        self,
        agent_id: str,
        cleanup_worktree: bool = True
    ) -> None:
        """
        Terminate a subagent and optionally cleanup its worktree.
        """
        state = self.subagents.get(agent_id)
        if not state:
            raise ValueError(f"Subagent {agent_id} not found")

        # Stop agent execution
        self._stop_agent_execution(agent_id)

        # Cleanup worktree if applicable
        if cleanup_worktree and state.worktree_id:
            self.worktree_manager.remove_worktree(
                state.worktree_id,
                force=False
            )

        # Update state
        state.status = SubagentStatus.TERMINATED

        # Emit event
        event = SubagentTerminatedEvent(
            agent_id=agent_id,
            timestamp=datetime.now(UTC)
        )
        self.journal.append(event)

    def merge_subagent_work(
        self,
        agent_id: str,
        target_branch: str = "main",
        strategy: str = "merge"
    ) -> None:
        """
        Merge subagent's worktree back to main branch.
        """
        state = self.subagents.get(agent_id)
        if not state or not state.worktree_id:
            raise ValueError(f"Subagent {agent_id} has no worktree")

        # Merge worktree
        self.worktree_manager.merge_worktree(
            worktree_id=state.worktree_id,
            target_branch=target_branch,
            strategy=strategy
        )

        # Terminate subagent
        self.terminate_subagent(agent_id, cleanup_worktree=True)
```

---

### 5. Worktree Events

```python
@dataclass
class WorktreeCreatedEvent:
    event_type: Literal["worktree_created"] = "worktree_created"
    worktree_id: str
    worktree_path: str
    branch_name: str
    agent_id: str
    task_id: str | None
    timestamp: datetime

@dataclass
class WorktreeRemovedEvent:
    event_type: Literal["worktree_removed"] = "worktree_removed"
    worktree_id: str
    forced: bool
    timestamp: datetime

@dataclass
class WorktreeMergedEvent:
    event_type: Literal["worktree_merged"] = "worktree_merged"
    worktree_id: str
    target_branch: str
    strategy: str
    timestamp: datetime

@dataclass
class SubagentSpawnedEvent:
    event_type: Literal["subagent_spawned"] = "subagent_spawned"
    agent_id: str
    agent_type: str
    isolation_level: IsolationLevel
    worktree_id: str | None
    task_id: str | None
    timestamp: datetime

@dataclass
class SubagentTerminatedEvent:
    event_type: Literal["subagent_terminated"] = "subagent_terminated"
    agent_id: str
    timestamp: datetime
```

---

### 6. Parallel Task Execution

**Use case:** Execute multiple tasks in parallel without git conflicts.

```python
class ParallelTaskExecutor:
    """Execute multiple tasks in parallel using worktrees."""

    def __init__(
        self,
        task_manager: TaskManager,
        subagent_manager: SubagentManager,
        worktree_manager: WorktreeManager
    ):
        self.task_manager = task_manager
        self.subagent_manager = subagent_manager
        self.worktree_manager = worktree_manager

    def execute_tasks_parallel(
        self,
        task_ids: list[str],
        agent_type: str = "implement"
    ) -> dict[str, str]:
        """
        Execute multiple tasks in parallel, each in its own worktree.

        Returns: dict mapping task_id -> agent_id
        """
        agent_ids = {}

        for task_id in task_ids:
            # Get task state
            task_state = self.task_manager.projection.task_states.get(task_id)
            if not task_state:
                continue

            # Create worktree config
            worktree_config = WorktreeConfig(
                worktree_base_dir=Path("../reins-worktrees"),
                worktree_name=task_id,
                branch_name=task_state.branch,
                base_branch=task_state.base_branch,
                create_branch=True,
                copy_files=[".reins/.developer", ".reins/config.yaml"],
                post_create_commands=["pip install -e ."],
                verify_commands=["python -c 'import reins'"],
                cleanup_on_success=True,
                cleanup_on_failure=False
            )

            # Spawn subagent with worktree isolation
            agent_id = self.subagent_manager.spawn_subagent(
                SubagentConfig(
                    agent_id=generate_ulid(),
                    agent_type=agent_type,
                    isolation_level=IsolationLevel.WORKTREE,
                    worktree_config=worktree_config,
                    task_id=task_id,
                    node_id=None,
                    inherited_grants=[],
                    capability_restrictions=set(),
                    context_manifest=None,
                    timeout_seconds=3600,
                    auto_cleanup=True
                )
            )

            agent_ids[task_id] = agent_id

        return agent_ids

    def wait_for_completion(
        self,
        agent_ids: list[str],
        timeout_seconds: int = 3600
    ) -> dict[str, SubagentStatus]:
        """Wait for all agents to complete."""
        start_time = time.time()
        statuses = {}

        while time.time() - start_time < timeout_seconds:
            all_done = True
            for agent_id in agent_ids:
                state = self.subagent_manager.subagents.get(agent_id)
                if not state:
                    continue

                if state.status in [SubagentStatus.RUNNING, SubagentStatus.SPAWNING]:
                    all_done = False
                else:
                    statuses[agent_id] = state.status

            if all_done:
                break

            time.sleep(1)

        return statuses
```

---

## C. Critical Review

### 1. Does this break "cheap operations stay cheap"?

**Assessment:** NO for normal operations, YES for worktree creation

**Cheap operations:**

- Spawn subagent without worktree: O(1) process spawn
- Check subagent status: O(1) dict lookup
- List subagents: O(n) where n = active subagents

**Expensive operations:**

- Create worktree: O(repo_size) git operation + file copy
- Remove worktree: O(1) git operation
- Merge worktree: O(commits) git operation

**Mitigation:**

- Worktree creation is async, doesn't block orchestrator
- Use worktrees only for parallel execution, not default
- Cache worktrees for reuse (future optimization)

### 2. Does this conflict with existing subagent system?

**Assessment:** NO, it extends it

- Worktree is one isolation level among many
- SubagentManager already handles spawn/terminate
- Worktree is optional, not required
- Existing NONE and PROCESS isolation still work

### 3. Does this support audit/replay?

**Assessment:** YES

- All worktree operations are events
- Can replay journal to see worktree lifecycle
- Worktree state tracked in projection
- Merge operations auditable

### 4. Does this support checkpoint/hydrate?

**Assessment:** PARTIAL

**Checkpoint:**

- Can checkpoint SubagentState (includes worktree_id)
- Can checkpoint WorktreeState
- Cannot checkpoint git worktree itself (filesystem state)

**Hydrate:**

- Can restore SubagentState
- Can restore WorktreeState
- Must verify worktree still exists on disk
- If worktree missing, fail hydrate or recreate

**Mitigation:**

- V1: Fail hydrate if worktree missing
- V2: Add worktree snapshot/restore

### 5. What happens on crash?

**Assessment:** Orphaned worktrees

**Scenarios:**

- Process crashes → worktrees remain on disk
- Agent fails → worktree not cleaned up
- Merge fails → worktree in inconsistent state

**Mitigation:**

- Periodic cleanup of idle worktrees
- On startup, scan for orphaned worktrees
- Mark worktrees with metadata file (`.reins-worktree.json`)
- Cleanup command: `reins worktree cleanup --all`

### 6. Can this scale to 10+ parallel agents?

**Assessment:** YES with limits

**Limits:**

- Disk space: Each worktree is full repo copy
- File descriptors: Each worktree has open files
- Git performance: Many worktrees slow git operations

**Mitigation:**

- Limit max concurrent worktrees (e.g., 10)
- Use shallow clones for worktrees (future)
- Use sparse checkouts (future)
- Monitor disk usage

---

## D. V1 Implementation Plan

### Phase 1: Worktree Manager (Week 1)

**Components:**

1. WorktreeConfig, WorktreeState dataclasses
2. WorktreeManager (create, remove, list)
3. Worktree events

**Deliverables:**

- Can create/remove worktrees
- Events written to journal
- Tests: worktree lifecycle

**Deferred:**

- Merge operations
- Cleanup automation
- Verification hooks

### Phase 2: Subagent Integration (Week 2)

**Components:**

1. IsolationLevel enum
2. SubagentConfig with worktree support
3. SubagentManager.spawn_subagent with WORKTREE isolation

**Deliverables:**

- Can spawn subagent in worktree
- Subagent executes in isolated directory
- Tests: subagent with worktree

**Deferred:**

- Grant inheritance in worktrees
- Context injection in worktrees

### Phase 3: Parallel Execution (Week 3)

**Components:**

1. ParallelTaskExecutor
2. execute_tasks_parallel()
3. wait_for_completion()

**Deliverables:**

- Can execute multiple tasks in parallel
- Each task in separate worktree
- Tests: parallel execution

**Deferred:**

- Merge automation
- Conflict resolution
- Progress tracking

### Phase 4: Cleanup and Recovery (Week 4)

**Components:**

1. cleanup_idle_worktrees()
2. Orphan detection on startup
3. Worktree metadata file

**Deliverables:**

- Idle worktrees cleaned up
- Orphaned worktrees detected
- Recovery from crashes
- Tests: cleanup, recovery

**Deferred:**

- Worktree snapshot/restore
- Shallow clones
- Sparse checkouts

---

## E. Success Criteria

**V1 is successful if:**

1. Can create git worktrees for subagent execution
2. Subagents execute in isolated worktree directories
3. Multiple subagents can work in parallel without conflicts
4. Worktrees are cleaned up after completion
5. Orphaned worktrees detected and cleaned
6. All operations auditable via events

**V1 does NOT need:**

- Merge automation (manual merge in v1)
- Worktree snapshot/restore (defer to v2)
- Shallow clones (defer to v2)
- Grant inheritance in worktrees (defer to v2)
- Context injection in worktrees (defer to v2)

---

## F. Migration from Trellis

**Trellis worktree structure:**

```
../trellis-worktrees/
├── 04-17-auth-feature/
│   ├── .trellis/.current-task
│   ├── .trellis/.developer
│   └── (full repo copy)
└── 04-17-payment-feature/
    └── (full repo copy)
```

**Reins worktree structure:**

```
../reins-worktrees/
├── 04-17-auth-feature/
│   ├── .reins-worktree.json  # Metadata
│   ├── .reins/.developer
│   └── (full repo copy)
└── 04-17-payment-feature/
    └── (full repo copy)
```

**Migration:**

- Keep same directory structure
- Add `.reins-worktree.json` metadata
- Use WorktreeManager instead of trellis scripts
- Gradual migration as new tasks created

---

## G. Open Questions

1. **Worktree reuse:** Should we reuse worktrees for same task? Or always create fresh?
2. **Merge strategy:** Default to merge, rebase, or squash?
3. **Cleanup timing:** Immediate after success or delayed?
4. **Disk space limits:** Hard limit on worktree count?
5. **Shallow clones:** Worth the complexity in v1?
6. **Sparse checkout:** Needed for large repos?
7. **Remote worktrees:** Support worktrees on remote machines?

---

## H. Next Steps

1. Review design with team
2. Create implementation tasks
3. Start Phase 1 (WorktreeManager)
4. Test with 2-3 parallel agents
5. Measure disk usage and performance
6. Document worktree workflow for users
