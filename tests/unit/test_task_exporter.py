"""Tests for task exporter."""

import json
import pytest
from pathlib import Path

from reins.export import TaskExporter
from reins.kernel.event.journal import EventJournal
from reins.task.context_jsonl import ContextMessage
from reins.task.manager import TaskManager
from reins.task.metadata import TaskStatus
from reins.task.projection import TaskContextProjection


@pytest.fixture
def journal(tmp_path):
    """Create journal for testing."""
    return EventJournal(tmp_path / "test-journal.jsonl")


@pytest.fixture
def task_projection():
    """Create task projection."""
    return TaskContextProjection()


@pytest.fixture
def task_manager(journal, task_projection):
    """Create task manager."""
    return TaskManager(journal, task_projection, run_id="test-run")


@pytest.fixture
def task_exporter(task_projection, tmp_path):
    """Create task exporter."""
    export_dir = tmp_path / "tasks"
    return TaskExporter(task_projection, export_dir)


@pytest.mark.asyncio
async def test_export_task(task_manager, task_exporter, tmp_path):
    """Test exporting a single task."""
    # Create task
    task_id = await task_manager.create_task(
        title="Test Task",
        task_type="backend",
        prd_content="Test PRD content",
        acceptance_criteria=["Criterion 1", "Criterion 2"],
        created_by="test",
        priority="P0",
        assignee="alice",
    )

    # Export task
    task_dir = task_exporter.export_task(task_id)
    assert task_dir is not None
    assert task_dir.exists()

    # Check task.json
    task_json_path = task_dir / "task.json"
    assert task_json_path.exists()

    with open(task_json_path, "r") as f:
        task_data = json.load(f)

    assert task_data["task_id"] == task_id
    assert task_data["title"] == "Test Task"
    assert task_data["task_type"] == "backend"
    assert task_data["priority"] == "P0"
    assert task_data["assignee"] == "alice"
    assert task_data["status"] == "pending"

    # Check prd.md
    prd_path = task_dir / "prd.md"
    assert prd_path.exists()

    prd_content = prd_path.read_text()
    assert "# Test Task" in prd_content
    assert "Test PRD content" in prd_content
    assert "Criterion 1" in prd_content
    assert "Criterion 2" in prd_content


@pytest.mark.asyncio
async def test_export_all_tasks(task_manager, task_exporter, tmp_path):
    """Test exporting all tasks."""
    # Create multiple tasks
    task1_id = await task_manager.create_task(
        title="Task 1",
        task_type="backend",
        prd_content="PRD 1",
        acceptance_criteria=["Done"],
        created_by="test",
        priority="P0",
        assignee="alice",
    )

    task2_id = await task_manager.create_task(
        title="Task 2",
        task_type="frontend",
        prd_content="PRD 2",
        acceptance_criteria=["Done"],
        created_by="test",
        priority="P1",
        assignee="bob",
    )

    # Export all
    exported_dirs = task_exporter.export_all()
    assert len(exported_dirs) == 2

    # Check both tasks were exported
    task_ids = {d.name for d in exported_dirs}
    assert task1_id in task_ids
    assert task2_id in task_ids


@pytest.mark.asyncio
async def test_export_task_nonexistent(task_exporter):
    """Test exporting nonexistent task."""
    result = task_exporter.export_task("nonexistent-task")
    assert result is None


@pytest.mark.asyncio
async def test_export_context(task_manager, task_exporter, tmp_path):
    """Test exporting agent context."""
    # Create task
    task_id = await task_manager.create_task(
        title="Test Task",
        task_type="backend",
        prd_content="Test PRD",
        acceptance_criteria=["Done"],
        created_by="test",
        priority="P0",
        assignee="alice",
    )

    # Create context messages
    messages = [
        ContextMessage(role="system", content="System message"),
        ContextMessage(role="user", content="User message"),
        ContextMessage(role="assistant", content="Assistant message"),
    ]

    # Export context
    jsonl_path = task_exporter.export_context(task_id, "implement", messages)
    assert jsonl_path is not None
    assert jsonl_path.exists()

    # Verify content
    lines = jsonl_path.read_text().strip().split("\n")
    assert len(lines) == 3

    # Parse and verify
    for i, line in enumerate(lines):
        data = json.loads(line)
        assert data["role"] == messages[i].role
        assert data["content"] == messages[i].content


@pytest.mark.asyncio
async def test_export_context_nonexistent_task(task_exporter):
    """Test exporting context for nonexistent task."""
    messages = [ContextMessage(role="user", content="Test")]
    result = task_exporter.export_context("nonexistent", "implement", messages)
    assert result is None


@pytest.mark.asyncio
async def test_set_current_task(task_manager, task_exporter, tmp_path):
    """Test setting current task."""
    # Create task
    task_id = await task_manager.create_task(
        title="Test Task",
        task_type="backend",
        prd_content="Test PRD",
        acceptance_criteria=["Done"],
        created_by="test",
        priority="P0",
        assignee="alice",
    )

    # Set current task
    task_exporter.set_current_task(task_id)

    # Check .current-task file
    current_task_file = tmp_path / ".current-task"
    assert current_task_file.exists()

    content = current_task_file.read_text().strip()
    assert content == f"tasks/{task_id}"


@pytest.mark.asyncio
async def test_get_current_task(task_manager, task_exporter, tmp_path):
    """Test getting current task."""
    # Create task
    task_id = await task_manager.create_task(
        title="Test Task",
        task_type="backend",
        prd_content="Test PRD",
        acceptance_criteria=["Done"],
        created_by="test",
        priority="P0",
        assignee="alice",
    )

    # Set current task
    task_exporter.set_current_task(task_id)

    # Get current task
    current_id = task_exporter.get_current_task()
    assert current_id == task_id


@pytest.mark.asyncio
async def test_clear_current_task(task_manager, task_exporter, tmp_path):
    """Test clearing current task."""
    # Create task
    task_id = await task_manager.create_task(
        title="Test Task",
        task_type="backend",
        prd_content="Test PRD",
        acceptance_criteria=["Done"],
        created_by="test",
        priority="P0",
        assignee="alice",
    )

    # Set current task
    task_exporter.set_current_task(task_id)
    assert task_exporter.get_current_task() == task_id

    # Clear current task
    task_exporter.set_current_task(None)
    assert task_exporter.get_current_task() is None

    # Check file was removed
    current_task_file = tmp_path / ".current-task"
    assert not current_task_file.exists()


@pytest.mark.asyncio
async def test_get_current_task_no_file(task_exporter):
    """Test getting current task when no file exists."""
    current_id = task_exporter.get_current_task()
    assert current_id is None


@pytest.mark.asyncio
async def test_cleanup_orphans(task_manager, task_exporter, tmp_path):
    """Test cleaning up orphaned task directories."""
    # Create task
    task_id = await task_manager.create_task(
        title="Test Task",
        task_type="backend",
        prd_content="Test PRD",
        acceptance_criteria=["Done"],
        created_by="test",
        priority="P0",
        assignee="alice",
    )

    # Export task
    task_exporter.export_task(task_id)

    # Create orphaned directory
    orphan_dir = tmp_path / "tasks" / "orphan-task"
    orphan_dir.mkdir(parents=True)
    (orphan_dir / "task.json").write_text("{}")

    # Cleanup orphans
    removed = task_exporter.cleanup_orphans()
    assert len(removed) == 1
    assert removed[0].name == "orphan-task"
    assert not orphan_dir.exists()

    # Real task should still exist
    real_task_dir = tmp_path / "tasks" / task_id
    assert real_task_dir.exists()


@pytest.mark.asyncio
async def test_create_index(task_manager, task_exporter, tmp_path):
    """Test creating task index."""
    # Create tasks with different statuses
    task1_id = await task_manager.create_task(
        title="Pending Task",
        task_type="backend",
        prd_content="PRD 1",
        acceptance_criteria=["Done"],
        created_by="test",
        priority="P0",
        assignee="alice",
    )

    task2_id = await task_manager.create_task(
        title="In Progress Task",
        task_type="frontend",
        prd_content="PRD 2",
        acceptance_criteria=["Done"],
        created_by="test",
        priority="P1",
        assignee="bob",
    )

    # Start task2
    await task_manager.start_task(task2_id, assignee="bob")

    # Create index
    index_path = task_exporter.create_index()
    assert index_path.exists()

    # Check content
    content = index_path.read_text()
    assert "# Tasks" in content
    assert "Pending Task" in content
    assert "In Progress Task" in content
    assert "### Pending" in content
    assert "### In Progress" in content


@pytest.mark.asyncio
async def test_export_task_with_parent(task_manager, task_exporter, tmp_path):
    """Test exporting task with parent task."""
    # Create parent task
    parent_id = await task_manager.create_task(
        title="Parent Task",
        task_type="backend",
        prd_content="Parent PRD",
        acceptance_criteria=["Done"],
        created_by="test",
        priority="P0",
        assignee="alice",
    )

    # Create child task
    child_id = await task_manager.create_task(
        title="Child Task",
        task_type="backend",
        prd_content="Child PRD",
        acceptance_criteria=["Done"],
        created_by="test",
        priority="P1",
        assignee="alice",
        parent_task_id=parent_id,
    )

    # Export child task
    task_dir = task_exporter.export_task(child_id)
    assert task_dir is not None

    # Check prd.md includes parent reference
    prd_path = task_dir / "prd.md"
    prd_content = prd_path.read_text()
    assert f"Parent Task**: {parent_id}" in prd_content


@pytest.mark.asyncio
async def test_export_all_excludes_archived(task_manager, task_exporter):
    """Test that export_all excludes archived tasks by default."""
    # Create tasks
    task1_id = await task_manager.create_task(
        title="Active Task",
        task_type="backend",
        prd_content="PRD 1",
        acceptance_criteria=["Done"],
        created_by="test",
        priority="P0",
        assignee="alice",
    )

    task2_id = await task_manager.create_task(
        title="Archived Task",
        task_type="backend",
        prd_content="PRD 2",
        acceptance_criteria=["Done"],
        created_by="test",
        priority="P1",
        assignee="bob",
    )

    # Archive task2
    await task_manager.archive_task(task2_id)

    # Export all (default: exclude archived)
    exported_dirs = task_exporter.export_all(include_archived=False)
    assert len(exported_dirs) == 1
    assert exported_dirs[0].name == task1_id

    # Export all (include archived)
    exported_dirs = task_exporter.export_all(include_archived=True)
    assert len(exported_dirs) == 2
