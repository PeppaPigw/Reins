"""Integration test for subagent worktree isolation.

Tests the full workflow:
1. Spawn subagent with worktree isolation
2. Verify worktree is created
3. Complete subagent and verify worktree cleanup
4. Test failure and abort scenarios
"""

import pytest
from pathlib import Path

from reins.isolation.types import IsolationLevel, WorktreeConfig
from reins.isolation.worktree_manager import WorktreeManager
from reins.kernel.event.journal import EventJournal
from reins.kernel.snapshot.store import SnapshotStore
from reins.memory.checkpoint import CheckpointStore
from reins.policy.engine import PolicyEngine
from reins.subagent.manager import SubagentManager, SubagentSpec, SubagentStatus


@pytest.fixture
def journal(tmp_path):
    """Create journal for testing."""
    return EventJournal(tmp_path / "test-journal.jsonl")


@pytest.fixture
def snapshot_store(tmp_path):
    """Create snapshot store."""
    return SnapshotStore(tmp_path / "snapshots")


@pytest.fixture
def checkpoint_store(tmp_path):
    """Create checkpoint store."""
    return CheckpointStore(tmp_path / "checkpoints")


@pytest.fixture
def policy_engine():
    """Create policy engine."""
    return PolicyEngine()


@pytest.fixture
def worktree_manager(journal, tmp_path):
    """Create worktree manager."""
    return WorktreeManager(
        journal=journal,
        run_id="test-run",
        repo_root=tmp_path / "repo",
    )


@pytest.fixture
def subagent_manager(journal, snapshot_store, checkpoint_store, policy_engine, worktree_manager):
    """Create subagent manager with worktree support."""
    return SubagentManager(
        journal=journal,
        snapshot_store=snapshot_store,
        checkpoint_store=checkpoint_store,
        policy_engine=policy_engine,
        worktree_manager=worktree_manager,
    )


@pytest.mark.asyncio
async def test_spawn_subagent_with_worktree(subagent_manager, worktree_manager, tmp_path):
    """Test spawning a subagent with worktree isolation."""
    # Setup git repo
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    # Initialize git repo
    import subprocess
    subprocess.run(["git", "init"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_root, check=True)

    # Create initial commit
    (repo_root / "README.md").write_text("# Test Repo")
    subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_root, check=True)

    # Get current branch name
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    base_branch = result.stdout.strip()

    # Update worktree manager repo root
    worktree_manager._repo_root = repo_root

    # Create worktree config
    worktree_config = WorktreeConfig(
        worktree_base_dir=tmp_path / "worktrees",
        worktree_name="test-worktree",
        branch_name="feat/test-feature",
        base_branch=base_branch,
        create_branch=True,
        copy_files=[],
        post_create_commands=[],
        cleanup_on_success=True,
        cleanup_on_failure=False,
    )

    # Create subagent spec with worktree isolation
    spec = SubagentSpec(
        objective="Test objective",
        parent_run_id="parent-run-123",
        isolation_level=IsolationLevel.WORKTREE,
        worktree_config=worktree_config,
        task_id="test-task-123",
    )

    # Spawn subagent
    handle = await subagent_manager.spawn(spec)

    # Verify handle
    assert handle is not None
    assert handle.status == SubagentStatus.running
    assert handle.isolation_level == IsolationLevel.WORKTREE
    assert handle.worktree_id is not None

    # Verify worktree was created
    worktree_state = worktree_manager.get_worktree(handle.worktree_id)
    assert worktree_state is not None
    assert worktree_state.agent_id == handle.child_run_id
    assert worktree_state.task_id == "test-task-123"
    assert worktree_state.is_active

    # Verify worktree directory exists
    assert worktree_state.worktree_path.exists()


@pytest.mark.asyncio
async def test_cleanup_worktree_on_completion(subagent_manager, worktree_manager, tmp_path):
    """Test worktree cleanup when subagent completes successfully."""
    # Setup git repo
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    import subprocess
    subprocess.run(["git", "init"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_root, check=True)
    (repo_root / "README.md").write_text("# Test Repo")
    subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_root, check=True)

    # Get current branch name
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    base_branch = result.stdout.strip()

    worktree_manager._repo_root = repo_root

    # Create worktree config with cleanup_on_success=True
    worktree_config = WorktreeConfig(
        worktree_base_dir=tmp_path / "worktrees",
        worktree_name="test-worktree-cleanup",
        branch_name="feat/cleanup-test",
        base_branch=base_branch,
        create_branch=True,
        cleanup_on_success=True,
    )

    spec = SubagentSpec(
        objective="Test cleanup",
        parent_run_id="parent-run-456",
        isolation_level=IsolationLevel.WORKTREE,
        worktree_config=worktree_config,
    )

    # Spawn and complete
    handle = await subagent_manager.spawn(spec)
    worktree_id = handle.worktree_id

    # Verify worktree exists
    assert worktree_manager.get_worktree(worktree_id) is not None

    # Complete subagent
    await subagent_manager.complete(handle.handle_id, {"summary": "Success"})

    # Verify worktree was cleaned up
    assert worktree_manager.get_worktree(worktree_id) is None


@pytest.mark.asyncio
async def test_cleanup_worktree_on_failure(subagent_manager, worktree_manager, tmp_path):
    """Test worktree cleanup when subagent fails."""
    # Setup git repo
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    import subprocess
    subprocess.run(["git", "init"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_root, check=True)
    (repo_root / "README.md").write_text("# Test Repo")
    subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_root, check=True)

    # Get current branch name
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    base_branch = result.stdout.strip()

    worktree_manager._repo_root = repo_root

    # Create worktree config with cleanup_on_failure=True
    worktree_config = WorktreeConfig(
        worktree_base_dir=tmp_path / "worktrees",
        worktree_name="test-worktree-failure",
        branch_name="feat/failure-test",
        base_branch=base_branch,
        create_branch=True,
        cleanup_on_failure=True,
    )

    spec = SubagentSpec(
        objective="Test failure cleanup",
        parent_run_id="parent-run-789",
        isolation_level=IsolationLevel.WORKTREE,
        worktree_config=worktree_config,
    )

    # Spawn and fail
    handle = await subagent_manager.spawn(spec)
    worktree_id = handle.worktree_id

    # Verify worktree exists
    assert worktree_manager.get_worktree(worktree_id) is not None

    # Fail subagent
    await subagent_manager.fail(handle.handle_id, "Test failure")

    # Verify worktree was cleaned up
    assert worktree_manager.get_worktree(worktree_id) is None


@pytest.mark.asyncio
async def test_cleanup_worktree_on_abort(subagent_manager, worktree_manager, tmp_path):
    """Test worktree cleanup when subagent is aborted."""
    # Setup git repo
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    import subprocess
    subprocess.run(["git", "init"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_root, check=True)
    (repo_root / "README.md").write_text("# Test Repo")
    subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_root, check=True)

    # Get current branch name
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    base_branch = result.stdout.strip()

    worktree_manager._repo_root = repo_root

    # Create worktree config
    worktree_config = WorktreeConfig(
        worktree_base_dir=tmp_path / "worktrees",
        worktree_name="test-worktree-abort",
        branch_name="feat/abort-test",
        base_branch=base_branch,
        create_branch=True,
    )

    spec = SubagentSpec(
        objective="Test abort cleanup",
        parent_run_id="parent-run-abc",
        isolation_level=IsolationLevel.WORKTREE,
        worktree_config=worktree_config,
    )

    # Spawn and abort
    handle = await subagent_manager.spawn(spec)
    worktree_id = handle.worktree_id

    # Verify worktree exists
    assert worktree_manager.get_worktree(worktree_id) is not None

    # Abort subagent
    await subagent_manager.abort(handle.handle_id, "User aborted")

    # Verify worktree was cleaned up (abort always cleans up)
    assert worktree_manager.get_worktree(worktree_id) is None


@pytest.mark.asyncio
async def test_subagent_without_worktree(subagent_manager):
    """Test spawning a subagent without worktree isolation."""
    # Create spec without worktree
    spec = SubagentSpec(
        objective="Test without worktree",
        parent_run_id="parent-run-xyz",
        isolation_level=IsolationLevel.NONE,
    )

    # Spawn subagent
    handle = await subagent_manager.spawn(spec)

    # Verify handle
    assert handle is not None
    assert handle.status == SubagentStatus.running
    assert handle.isolation_level == IsolationLevel.NONE
    assert handle.worktree_id is None

    # Complete should work without worktree
    await subagent_manager.complete(handle.handle_id, {"summary": "Done"})
    assert handle.status == SubagentStatus.completed


@pytest.mark.asyncio
async def test_worktree_required_validation(subagent_manager):
    """Test that worktree isolation requires WorktreeManager."""
    # Create spec with worktree isolation but no config
    spec = SubagentSpec(
        objective="Test validation",
        parent_run_id="parent-run-validation",
        isolation_level=IsolationLevel.WORKTREE,
        worktree_config=None,  # Missing config
    )

    # Should raise ValueError
    with pytest.raises(ValueError, match="worktree_config required"):
        await subagent_manager.spawn(spec)


@pytest.mark.asyncio
async def test_worktree_manager_required_validation():
    """Test that worktree isolation requires WorktreeManager in SubagentManager."""
    from pathlib import Path

    # Create subagent manager WITHOUT worktree manager
    journal = EventJournal(Path("/tmp/test-journal.jsonl"))
    snapshot_store = SnapshotStore(Path("/tmp/snapshots"))
    checkpoint_store = CheckpointStore(Path("/tmp/checkpoints"))
    policy_engine = PolicyEngine()

    manager = SubagentManager(
        journal=journal,
        snapshot_store=snapshot_store,
        checkpoint_store=checkpoint_store,
        policy_engine=policy_engine,
        worktree_manager=None,  # No worktree manager
    )

    # Create spec with worktree isolation
    worktree_config = WorktreeConfig(
        worktree_base_dir=Path("/tmp/worktrees"),
        worktree_name="test",
        branch_name="feat/test",
        base_branch="main",
    )

    spec = SubagentSpec(
        objective="Test validation",
        parent_run_id="parent-run-validation",
        isolation_level=IsolationLevel.WORKTREE,
        worktree_config=worktree_config,
    )

    # Should raise ValueError
    with pytest.raises(ValueError, match="WorktreeManager required"):
        await manager.spawn(spec)
