"""Integration test for task management in orchestrator.

Tests the full task workflow:
1. Create task via orchestrator
2. Start task and set as active
3. Bootstrap session with task context
4. Complete task and clear active
"""

import pytest
from pathlib import Path

from reins.context.compiler_v2 import ContextCompilerV2
from reins.context.spec_projection import ContextSpecProjection
from reins.context.spec_registrar import SpecRegistrar
from reins.context.token_budget import TokenBudget
from reins.kernel.event.journal import EventJournal
from reins.kernel.orchestrator import RunOrchestrator
from reins.kernel.reducer.state import RunState
from reins.kernel.snapshot.store import SnapshotStore
from reins.memory.checkpoint import CheckpointStore
from reins.policy.engine import PolicyEngine
from reins.task.manager import TaskManager
from reins.task.projection import TaskContextProjection
from reins.task.metadata import TaskStatus


@pytest.fixture
def journal(tmp_path):
    """Create journal for testing."""
    return EventJournal(tmp_path / "test-journal.jsonl")


@pytest.fixture
def spec_projection(journal, tmp_path):
    """Create spec projection with sample specs."""
    import asyncio

    async def setup():
        # Create spec directory
        spec_dir = tmp_path / "specs"
        spec_dir.mkdir()
        backend_dir = spec_dir / "backend"
        backend_dir.mkdir()

        # Create standing law spec
        (backend_dir / "error-handling.yaml").write_text("""
spec_type: standing_law
scope: workspace
precedence: 100
visibility_tier: 0
required_capabilities: []
applicability: {}
content: |
  # Error Handling
  Always use structured error types.
""")

        # Create task contract spec (will match task scope)
        (backend_dir / "auth-task.yaml").write_text("""
spec_type: task_contract
scope: task:test-auth-task
precedence: 200
visibility_tier: 0
required_capabilities: []
applicability: {}
content: |
  # Task: Implement JWT Authentication
  Use RS256 algorithm.
""")

        # Import specs
        projection = ContextSpecProjection()
        registrar = SpecRegistrar(journal, run_id="test-run")
        await registrar.import_from_directory(spec_dir)

        # Apply events to projection
        async for event in journal.read_from("test-run"):
            projection.apply_event(event)

        return projection

    return asyncio.run(setup())


@pytest.fixture
def task_projection(journal):
    """Create task projection."""
    return TaskContextProjection()


@pytest.fixture
def task_manager(journal, task_projection):
    """Create task manager."""
    return TaskManager(journal, task_projection, run_id="test-run")


@pytest.fixture
def orchestrator(journal, spec_projection, task_manager, task_projection, tmp_path):
    """Create orchestrator with v2 components."""
    from reins.context.compiler import ContextCompiler

    # Create required components
    snapshot_store = SnapshotStore(tmp_path / "snapshots")
    checkpoint_store = CheckpointStore(tmp_path / "checkpoints")
    policy_engine = PolicyEngine()
    context_compiler = ContextCompiler()
    compiler_v2 = ContextCompilerV2(spec_projection)

    orch = RunOrchestrator(
        journal=journal,
        snapshot_store=snapshot_store,
        checkpoint_store=checkpoint_store,
        policy_engine=policy_engine,
        context_compiler=context_compiler,
        context_compiler_v2=compiler_v2,
        spec_projection=spec_projection,
        task_manager=task_manager,
        task_projection=task_projection,
    )

    # Initialize state
    orch._state = RunState(run_id="test-run")

    return orch


@pytest.mark.asyncio
async def test_create_task_via_orchestrator(orchestrator, task_projection):
    """Test creating a task through the orchestrator."""
    # Create task
    task_id = await orchestrator.create_task(
        title="Implement JWT authentication",
        task_type="backend",
        prd_content="Use RS256 algorithm and store tokens in Redis",
        acceptance_criteria=[
            "JWT tokens generated with RS256",
            "Tokens stored in Redis with TTL",
        ],
        priority="P0",
    )

    # Verify task was created
    assert task_id is not None

    # Verify task in projection
    task = task_projection.get_task(task_id)
    assert task is not None
    assert task.title == "Implement JWT authentication"
    assert task.task_type == "backend"
    assert task.status == TaskStatus.PENDING


@pytest.mark.asyncio
async def test_start_task_sets_active(orchestrator, task_projection):
    """Test starting a task sets it as active in orchestrator."""
    # Create task
    task_id = await orchestrator.create_task(
        title="Implement user login",
        task_type="backend",
        prd_content="Login endpoint with email/password",
        acceptance_criteria=["Login endpoint works"],
    )

    # Start task
    await orchestrator.start_task(task_id, assignee="test-agent")

    # Verify task is active in orchestrator
    assert orchestrator.get_active_task() == task_id

    # Verify task status updated
    task = task_projection.get_task(task_id)
    assert task.status == TaskStatus.IN_PROGRESS
    assert task.assignee == "test-agent"


@pytest.mark.asyncio
async def test_bootstrap_with_active_task(orchestrator, task_projection):
    """Test bootstrap_session loads active task context."""
    # Create and start task with specific ID
    task_id = "test-auth-task"  # Matches spec scope

    # Manually create task with specific ID
    from reins.task.metadata import TaskMetadata
    from datetime import datetime, UTC

    metadata = TaskMetadata(
        task_id=task_id,
        title="Implement JWT authentication",
        slug="jwt-auth",
        task_type="backend",
        prd_content="Use RS256 algorithm",
        acceptance_criteria=["RS256 tokens"],
        priority="P0",
        assignee=None,
        status=TaskStatus.PENDING,
        branch="feat/jwt-auth",
        base_branch="main",
        created_by="test",
        created_at=datetime.now(UTC),
    )

    # Add to projection manually
    task_projection._tasks[task_id] = metadata
    task_projection._event_history[task_id] = []
    task_projection._decisions[task_id] = []

    # Set as active
    orchestrator.set_active_task(task_id)

    # Bootstrap session (should auto-load task context)
    manifest_dict = orchestrator.bootstrap_session(
        token_budget=TokenBudget.default()
    )

    # Verify manifest includes task contract
    assert manifest_dict is not None
    assert len(manifest_dict["task_contract"]) == 1
    assert manifest_dict["task_contract"][0]["spec_id"] == "backend.auth-task"


@pytest.mark.asyncio
async def test_complete_task_clears_active(orchestrator, task_projection):
    """Test completing a task clears it from active."""
    # Create and start task
    task_id = await orchestrator.create_task(
        title="Implement password reset",
        task_type="backend",
        prd_content="Password reset flow",
        acceptance_criteria=["Reset works"],
    )

    await orchestrator.start_task(task_id, assignee="test-agent")

    # Verify task is active
    assert orchestrator.get_active_task() == task_id

    # Complete task
    await orchestrator.complete_task(task_id, outcome={"files_modified": 3})

    # Verify task is no longer active
    assert orchestrator.get_active_task() is None

    # Verify task status updated
    task = task_projection.get_task(task_id)
    assert task.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_get_active_task_context(orchestrator, task_projection):
    """Test getting active task context."""
    # Create task
    task_id = await orchestrator.create_task(
        title="Implement user registration",
        task_type="frontend",
        prd_content="Registration form with validation",
        acceptance_criteria=["Form validates", "API integration works"],
        priority="P1",
    )

    await orchestrator.start_task(task_id, assignee="test-agent")

    # Get active task context
    context = orchestrator.get_active_task_context()

    # Verify context
    assert context is not None
    assert context["task_id"] == task_id
    assert context["task_type"] == "frontend"
    assert context["title"] == "Implement user registration"
    assert context["prd_content"] == "Registration form with validation"
    assert context["priority"] == "P1"
    assert context["assignee"] == "test-agent"
    assert context["status"] == "in_progress"
