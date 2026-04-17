# Task Management System - Reins Native Design

**Date:** 2026-04-17  
**Status:** Design Complete, Ready for Implementation  
**Goal:** Absorb trellis's task management patterns as native Reins workflow primitives

---

## A. Architectural Conclusion

**Is this direction stable?** YES.

Trellis's task management has three core concepts:
1. **Task metadata** (PRD, assignee, status, branch)
2. **Task context** (JSONL files for agent state)
3. **Current task pointer** (`.current-task` file)

These map cleanly to Reins primitives:
1. Task metadata → **WorkflowGraph nodes with extended metadata**
2. Task context → **Event journal + snapshot state**
3. Current task pointer → **Active run in orchestrator state**

**Key insight:** Don't create a parallel task system. Make tasks first-class workflow nodes.

---

## B. Core Design

### 1. Task as Workflow Node

**Current Reins workflow:**
```python
@dataclass
class WorkflowNode:
    node_id: str
    node_type: NodeType  # TASK | DECISION | PARALLEL | SEQUENTIAL
    name: str
    dependencies: list[str]
    metadata: dict[str, Any]
```

**Extended for task management:**
```python
@dataclass
class TaskNode(WorkflowNode):
    """A workflow node representing a development task."""
    node_type: Literal[NodeType.TASK] = NodeType.TASK
    
    # Task-specific metadata
    task_metadata: TaskMetadata
    
@dataclass
class TaskMetadata:
    """Task management metadata."""
    # Identity
    task_id: str  # e.g., "04-17-auth-feature"
    slug: str  # e.g., "auth-feature"
    
    # Assignment
    assignee: str  # "claude-agent" | "human" | "unassigned"
    priority: str  # "P0" | "P1" | "P2" | "P3"
    
    # Git integration
    branch: str  # "feat/auth-feature"
    base_branch: str  # "main"
    
    # Status tracking
    status: TaskStatus  # PENDING | IN_PROGRESS | BLOCKED | COMPLETED | FAILED
    
    # Requirements
    prd_content: str  # Product requirements document
    acceptance_criteria: list[str]
    
    # Context
    task_type: str  # "backend" | "frontend" | "fullstack"
    package: str | None  # "api" | "web" | None
    
    # Timestamps
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    
    # Audit
    created_by: str
    last_modified_by: str

class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
```

**Why this works:**
- Tasks are already nodes in workflow graph
- Node state tracker already handles status transitions
- Dependencies already tracked in graph edges
- No parallel state management system needed

---

### 2. Task Context Storage

**Trellis approach:**
- JSONL files per agent (`implement.jsonl`, `check.jsonl`)
- Stores agent conversation history
- Loaded by hooks before agent invocation

**Reins approach:**
- Event journal already stores all agent interactions
- Snapshot state already stores current task state
- No separate JSONL files needed

**Task context = projection of journal events:**

```python
class TaskContextProjection:
    """Projects task-relevant events from journal."""
    
    def __init__(self):
        self.task_states: dict[str, TaskState] = {}
        self.task_events: dict[str, list[Event]] = defaultdict(list)
    
    def apply_event(self, event: Event) -> None:
        """Update projection from event."""
        if event.event_type == "task_created":
            self._handle_task_created(event)
        elif event.event_type == "task_started":
            self._handle_task_started(event)
        elif event.event_type == "task_completed":
            self._handle_task_completed(event)
        elif event.event_type == "command_submitted":
            # Track commands associated with task
            if event.payload.get("task_id"):
                task_id = event.payload["task_id"]
                self.task_events[task_id].append(event)
    
    def get_task_context(self, task_id: str) -> TaskContext:
        """Get all context for a task."""
        return TaskContext(
            task_state=self.task_states.get(task_id),
            events=self.task_events.get(task_id, []),
            prd=self._extract_prd(task_id),
            decisions=self._extract_decisions(task_id),
            failures=self._extract_failures(task_id)
        )

@dataclass
class TaskContext:
    """Complete context for a task."""
    task_state: TaskState
    events: list[Event]  # All events related to this task
    prd: str  # Requirements document
    decisions: list[Decision]  # Open decisions
    failures: list[FailureRecord]  # Previous failures/retries
```

**Benefits:**
- Single source of truth (journal)
- No file synchronization issues
- Automatic audit trail
- Replay-friendly

---

### 3. Current Task Tracking

**Trellis approach:**
- `.trellis/.current-task` file with path to task directory
- Read by hooks to inject task context

**Reins approach:**
- Active run in orchestrator state
- No file needed, state is in-memory + checkpointed

```python
@dataclass
class OrchestratorState:
    """Orchestrator's current state."""
    active_run_id: str | None
    active_task_id: str | None  # NEW: track current task
    active_workflow_id: str | None
    active_node_id: str | None
    
    pending_approvals: list[ApprovalRequest]
    open_decisions: list[Decision]
    
    # Checkpoint data
    last_checkpoint_at: datetime
    checkpoint_seq: int

class Orchestrator:
    def set_active_task(self, task_id: str) -> None:
        """Set the current task."""
        self.state.active_task_id = task_id
        self._emit_event(TaskActivatedEvent(task_id=task_id))
    
    def get_active_task(self) -> TaskState | None:
        """Get current task state."""
        if not self.state.active_task_id:
            return None
        return self.task_projection.task_states.get(self.state.active_task_id)
    
    def clear_active_task(self) -> None:
        """Clear current task."""
        if self.state.active_task_id:
            self._emit_event(TaskDeactivatedEvent(task_id=self.state.active_task_id))
        self.state.active_task_id = None
```

**Benefits:**
- No file I/O on hot path
- State is checkpointed with rest of orchestrator state
- Survives process restart via checkpoint
- Auditable via events

---

### 4. Task Lifecycle Events

```python
@dataclass
class TaskCreatedEvent:
    event_type: Literal["task_created"] = "task_created"
    task_id: str
    metadata: TaskMetadata
    created_by: str
    timestamp: datetime

@dataclass
class TaskStartedEvent:
    event_type: Literal["task_started"] = "task_started"
    task_id: str
    assignee: str
    timestamp: datetime

@dataclass
class TaskCompletedEvent:
    event_type: Literal["task_completed"] = "task_completed"
    task_id: str
    outcome: dict[str, Any]  # Results, artifacts, etc.
    timestamp: datetime

@dataclass
class TaskFailedEvent:
    event_type: Literal["task_failed"] = "task_failed"
    task_id: str
    error: str
    retry_count: int
    timestamp: datetime

@dataclass
class TaskBlockedEvent:
    event_type: Literal["task_blocked"] = "task_blocked"
    task_id: str
    blocked_by: list[str]  # Other task IDs or decision IDs
    reason: str
    timestamp: datetime

@dataclass
class TaskActivatedEvent:
    event_type: Literal["task_activated"] = "task_activated"
    task_id: str
    timestamp: datetime

@dataclass
class TaskDeactivatedEvent:
    event_type: Literal["task_deactivated"] = "task_deactivated"
    task_id: str
    timestamp: datetime

@dataclass
class TaskPRDUpdatedEvent:
    event_type: Literal["task_prd_updated"] = "task_prd_updated"
    task_id: str
    prd_content: str
    updated_by: str
    timestamp: datetime
```

---

### 5. Task Manager Component

```python
class TaskManager:
    """Manages task lifecycle and state."""
    
    def __init__(
        self,
        journal: EventJournal,
        workflow_builder: TaskGraphBuilder,
        orchestrator: Orchestrator
    ):
        self.journal = journal
        self.workflow_builder = workflow_builder
        self.orchestrator = orchestrator
        self.projection = TaskContextProjection()
    
    def create_task(
        self,
        title: str,
        task_type: str,
        prd_content: str,
        acceptance_criteria: list[str],
        created_by: str,
        **kwargs
    ) -> str:
        """Create a new task."""
        # Generate task ID
        date_prefix = datetime.now().strftime("%m-%d")
        slug = self._slugify(title)
        task_id = f"{date_prefix}-{slug}"
        
        # Create metadata
        metadata = TaskMetadata(
            task_id=task_id,
            slug=slug,
            assignee=kwargs.get("assignee", "unassigned"),
            priority=kwargs.get("priority", "P1"),
            branch=f"feat/{slug}",
            base_branch=kwargs.get("base_branch", "main"),
            status=TaskStatus.PENDING,
            prd_content=prd_content,
            acceptance_criteria=acceptance_criteria,
            task_type=task_type,
            package=kwargs.get("package"),
            created_at=datetime.now(UTC),
            started_at=None,
            completed_at=None,
            created_by=created_by,
            last_modified_by=created_by
        )
        
        # Emit event
        event = TaskCreatedEvent(
            task_id=task_id,
            metadata=metadata,
            created_by=created_by,
            timestamp=datetime.now(UTC)
        )
        self.journal.append(event)
        
        # Create workflow node
        self.workflow_builder.add_node(
            graph_id="main",
            node_id=task_id,
            node_type=NodeType.TASK,
            name=title
        )
        
        return task_id
    
    def start_task(self, task_id: str, assignee: str) -> None:
        """Start working on a task."""
        event = TaskStartedEvent(
            task_id=task_id,
            assignee=assignee,
            timestamp=datetime.now(UTC)
        )
        self.journal.append(event)
        
        # Set as active task
        self.orchestrator.set_active_task(task_id)
    
    def complete_task(self, task_id: str, outcome: dict[str, Any]) -> None:
        """Mark task as completed."""
        event = TaskCompletedEvent(
            task_id=task_id,
            outcome=outcome,
            timestamp=datetime.now(UTC)
        )
        self.journal.append(event)
        
        # Clear active task if this was it
        if self.orchestrator.state.active_task_id == task_id:
            self.orchestrator.clear_active_task()
    
    def update_prd(self, task_id: str, prd_content: str, updated_by: str) -> None:
        """Update task PRD."""
        event = TaskPRDUpdatedEvent(
            task_id=task_id,
            prd_content=prd_content,
            updated_by=updated_by,
            timestamp=datetime.now(UTC)
        )
        self.journal.append(event)
    
    def get_task_context(self, task_id: str) -> TaskContext:
        """Get complete context for a task."""
        return self.projection.get_task_context(task_id)
    
    def list_tasks(
        self,
        status: TaskStatus | None = None,
        assignee: str | None = None
    ) -> list[TaskState]:
        """List tasks with optional filtering."""
        tasks = list(self.projection.task_states.values())
        
        if status:
            tasks = [t for t in tasks if t.status == status]
        if assignee:
            tasks = [t for t in tasks if t.assignee == assignee]
        
        return sorted(tasks, key=lambda t: t.created_at, reverse=True)
```

---

### 6. Integration with Context Injection

**Task context feeds into ContextCompiler:**

```python
class ContextCompiler:
    def seed_context(
        self,
        task_state: TaskState | None,  # From TaskManager
        granted_capabilities: set[str],
        token_budget: TokenBudget
    ) -> ContextAssemblyManifest:
        """Assemble seed context including task contract."""
        
        # Resolve specs (standing law + task contract)
        query = SpecQuery(
            scope="workspace",
            task_type=task_state.task_type if task_state else None,
            run_phase=None,
            actor_type=None,
            path=None,
            granted_capabilities=granted_capabilities,
            visibility_tier=0
        )
        resolved = self.projection.resolve(query)
        
        # Separate by type
        standing_law = [s for s in resolved if s.spec_type == "standing_law"]
        task_contract = [s for s in resolved if s.spec_type == "task_contract"]
        
        # If task is active, inject PRD as task contract
        if task_state:
            task_contract.append(ResolvedSpec(
                spec_id=f"task-contract-{task_state.task_id}",
                spec_type="task_contract",
                precedence=100,  # High precedence
                content=self._format_task_contract(task_state),
                match_reason="active_task"
            ))
        
        # Allocate tokens and assemble
        # ... (rest of seed_context logic)
    
    def _format_task_contract(self, task_state: TaskState) -> str:
        """Format task state as contract for agent."""
        return f"""# Task: {task_state.task_id}

## Requirements
{task_state.prd_content}

## Acceptance Criteria
{chr(10).join(f"- [ ] {c}" for c in task_state.acceptance_criteria)}

## Task Type
{task_state.task_type}

## Status
{task_state.status.value}
"""
```

---

### 7. Task Subtasks and Dependencies

**Trellis supports subtasks via `--parent` flag.**

**Reins approach: Use workflow graph edges:**

```python
class TaskManager:
    def create_subtask(
        self,
        parent_task_id: str,
        title: str,
        **kwargs
    ) -> str:
        """Create a subtask of an existing task."""
        # Create task normally
        subtask_id = self.create_task(title=title, **kwargs)
        
        # Add dependency edge
        self.workflow_builder.add_edge(
            graph_id="main",
            from_node=subtask_id,
            to_node=parent_task_id
        )
        
        return subtask_id
    
    def get_subtasks(self, parent_task_id: str) -> list[str]:
        """Get all subtasks of a task."""
        graph = self.workflow_builder.get_graph("main")
        if not graph:
            return []
        
        # Find nodes that have edge to parent
        subtasks = []
        for from_node, to_node in graph.edges:
            if to_node == parent_task_id:
                subtasks.append(from_node)
        
        return subtasks
    
    def is_task_ready(self, task_id: str) -> bool:
        """Check if task is ready to start (all dependencies completed)."""
        graph = self.workflow_builder.get_graph("main")
        if not graph:
            return True
        
        node = graph.nodes.get(task_id)
        if not node:
            return False
        
        # Check all dependencies
        for dep_id in node.dependencies:
            dep_state = self.projection.task_states.get(dep_id)
            if not dep_state or dep_state.status != TaskStatus.COMPLETED:
                return False
        
        return True
```

---

## C. Migration from Trellis

**Current trellis structure:**
```
.trellis/tasks/
├── 04-17-auth-feature/
│   ├── task.json
│   ├── prd.md
│   ├── info.md
│   ├── implement.jsonl
│   ├── check.jsonl
│   └── debug.jsonl
└── .current-task
```

**Reins structure:**
```
Event Journal (in-memory + persisted)
├── TaskCreatedEvent(task_id="04-17-auth-feature", metadata=...)
├── TaskStartedEvent(task_id="04-17-auth-feature", ...)
├── CommandSubmittedEvent(task_id="04-17-auth-feature", ...)
└── TaskCompletedEvent(task_id="04-17-auth-feature", ...)

Orchestrator State (checkpointed)
├── active_task_id: "04-17-auth-feature"
└── ...

TaskContextProjection (in-memory)
├── task_states["04-17-auth-feature"] = TaskState(...)
└── task_events["04-17-auth-feature"] = [Event, Event, ...]
```

**Migration steps:**

1. **Import existing tasks:**
```python
def import_trellis_tasks(trellis_tasks_dir: Path) -> None:
    """Import tasks from .trellis/tasks/ into Reins."""
    for task_dir in trellis_tasks_dir.iterdir():
        if not task_dir.is_dir():
            continue
        
        # Read task.json
        task_json = json.loads((task_dir / "task.json").read_text())
        
        # Read prd.md
        prd_content = (task_dir / "prd.md").read_text() if (task_dir / "prd.md").exists() else ""
        
        # Create task in Reins
        task_manager.create_task(
            title=task_json["title"],
            task_type=task_json.get("package", "backend"),
            prd_content=prd_content,
            acceptance_criteria=[],
            created_by="migration",
            assignee=task_json.get("assignee", "unassigned"),
            priority=task_json.get("priority", "P1")
        )
```

2. **Parallel operation:**
- Keep `.trellis/tasks/` for reference
- New tasks created in Reins
- Gradually migrate workflows

3. **Deprecate trellis:**
- Once all active tasks in Reins
- Archive `.trellis/tasks/`
- Remove trellis scripts

---

## D. Critical Review

### 1. Does this break "cheap operations stay cheap"?

**Assessment:** NO

- Task creation: O(1) event append
- Task lookup: O(1) projection dict access
- Task list: O(n) where n = total tasks (typically <100)
- Active task check: O(1) orchestrator state access

**No file I/O on hot paths.**

### 2. Does this conflict with workflow system?

**Assessment:** NO, it enhances it

- Tasks ARE workflow nodes
- No parallel state management
- Workflow graph already handles dependencies
- Node state tracker already handles status

### 3. Does this support audit/replay?

**Assessment:** YES

- All task operations are events
- Can replay journal to reconstruct task history
- Projection rebuilds from events
- Checkpoint includes active task ID

### 4. Does this support checkpoint/hydrate?

**Assessment:** YES

- Orchestrator state includes active_task_id
- Checkpoint serializes state
- Hydrate restores active task
- No file synchronization needed

### 5. Can this scale to 1000+ tasks?

**Assessment:** YES with indexes

- V1: Linear scan acceptable for <100 tasks
- V2: Add indexes (by_status, by_assignee, by_priority)
- Projection is in-memory, fast queries
- Journal append is O(1)

---

## E. V1 Implementation Plan

### Phase 1: Events and Projection (Week 1)

**Components:**
1. Task event types
2. TaskMetadata dataclass
3. TaskContextProjection
4. Basic TaskManager (create, start, complete)

**Deliverables:**
- Can create tasks via TaskManager
- Events written to journal
- Projection tracks task states
- Tests: task lifecycle, projection build

---

### Phase 2: Integration with Orchestrator (Week 2)

**Components:**
1. Add active_task_id to OrchestratorState
2. set_active_task / get_active_task / clear_active_task
3. Checkpoint/hydrate support

**Deliverables:**
- Orchestrator tracks active task
- Active task survives checkpoint/hydrate
- Tests: active task tracking, checkpoint/hydrate

---

### Phase 3: Context Integration (Week 3)

**Components:**
1. TaskContext dataclass
2. get_task_context() in TaskManager
3. Integration with ContextCompiler.seed_context()

**Deliverables:**
- Task PRD injected as task contract
- Agent sees task requirements in context
- Tests: context assembly with task

---

### Phase 4: Dependencies and Subtasks (Week 4)

**Components:**
1. create_subtask()
2. get_subtasks()
3. is_task_ready()
4. Task blocking/unblocking

**Deliverables:**
- Can create task hierarchies
- Dependencies tracked in workflow graph
- Blocked tasks cannot start
- Tests: subtasks, dependencies, blocking

---

## F. Success Criteria

**V1 is successful if:**

1. Tasks can be created with PRD and acceptance criteria
2. Tasks are stored as events in journal
3. Active task tracked in orchestrator state
4. Task PRD injected into agent context
5. Task dependencies tracked in workflow graph
6. Checkpoint/hydrate preserves active task
7. All operations are auditable via events

**V1 does NOT need:**
- Trellis migration (defer to v2)
- Git branch integration (defer to v2)
- Task archival (defer to v2)
- Advanced queries (defer to v2)
