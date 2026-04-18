"""Integration tests for session-start hook."""

import json
import subprocess
from pathlib import Path

import pytest

from reins.export import TaskExporter
from reins.kernel.event.journal import EventJournal
from reins.task.manager import TaskManager
from reins.task.projection import TaskContextProjection


@pytest.fixture
def test_repo(tmp_path):
    """Create a test repository structure."""
    # Create .reins directory structure
    reins_dir = tmp_path / ".reins"
    reins_dir.mkdir()

    (reins_dir / "tasks").mkdir()
    (reins_dir / "spec").mkdir()

    # Create spec directories
    (reins_dir / "spec" / "backend").mkdir()
    (reins_dir / "spec" / "frontend").mkdir()
    (reins_dir / "spec" / "guides").mkdir()

    return tmp_path


@pytest.fixture
def hook_script():
    """Get path to session-start hook script."""
    # Assuming tests are run from repo root
    hook_path = Path(__file__).parent.parent.parent / "hooks" / "claude-code" / "session-start.py"
    if not hook_path.exists():
        pytest.skip(f"Hook script not found at {hook_path}")
    return hook_path


@pytest.mark.asyncio
async def test_session_start_hook_no_current_task(test_repo, hook_script):
    """Test hook when no current task is set."""
    result = subprocess.run(
        ["python3", str(hook_script)],
        cwd=test_repo,
        capture_output=True,
        text=True,
        timeout=5,
    )

    # Should succeed with no output (no current task)
    assert result.returncode == 0
    assert result.stdout == ""


@pytest.mark.asyncio
async def test_session_start_hook_with_task(test_repo, hook_script):
    """Test hook with an active task."""
    # Create task using TaskManager
    journal = EventJournal(test_repo / ".reins" / "journal.jsonl")
    projection = TaskContextProjection()
    manager = TaskManager(journal, projection, run_id="test")

    task_id = await manager.create_task(
        title="Test Task",
        task_type="backend",
        prd_content="This is a test PRD",
        acceptance_criteria=["Criterion 1", "Criterion 2"],
        created_by="test",
        priority="P0",
        assignee="test-user",
    )

    # Export task
    exporter = TaskExporter(projection, test_repo / ".reins" / "tasks")
    exporter.export_task(task_id)
    exporter.set_current_task(task_id)

    # Run hook
    result = subprocess.run(
        ["python3", str(hook_script)],
        cwd=test_repo,
        capture_output=True,
        text=True,
        timeout=5,
    )

    # Should succeed with output
    assert result.returncode == 0
    assert result.stdout != ""

    # Check output contains expected elements
    assert "<session-context>" in result.stdout
    assert "<current-task>" in result.stdout
    assert "Test Task" in result.stdout
    assert task_id in result.stdout
    assert "backend" in result.stdout
    assert "P0" in result.stdout
    assert "This is a test PRD" in result.stdout
    assert "Criterion 1" in result.stdout


@pytest.mark.asyncio
async def test_session_start_hook_with_specs(test_repo, hook_script):
    """Test hook loads relevant specs."""
    # Create task
    journal = EventJournal(test_repo / ".reins" / "journal.jsonl")
    projection = TaskContextProjection()
    manager = TaskManager(journal, projection, run_id="test")

    task_id = await manager.create_task(
        title="Backend Task",
        task_type="backend",
        prd_content="Backend work",
        acceptance_criteria=["Done"],
        created_by="test",
        priority="P0",
        assignee="test-user",
    )

    # Export task
    exporter = TaskExporter(projection, test_repo / ".reins" / "tasks")
    exporter.export_task(task_id)
    exporter.set_current_task(task_id)

    # Create backend spec
    backend_spec_dir = test_repo / ".reins" / "spec" / "backend"
    backend_index = backend_spec_dir / "index.md"
    backend_index.write_text("""# Backend Specifications

## Pre-Development Checklist

Before starting backend work, read:
- [ ] error-handling.md
- [ ] conventions.md
""")

    # Create guides spec
    guides_spec_dir = test_repo / ".reins" / "spec" / "guides"
    guides_index = guides_spec_dir / "index.md"
    guides_index.write_text("""# Development Guides

## General Guidelines

- Follow SOLID principles
- Write tests first
""")

    # Run hook
    result = subprocess.run(
        ["python3", str(hook_script)],
        cwd=test_repo,
        capture_output=True,
        text=True,
        timeout=5,
    )

    # Should succeed with specs
    assert result.returncode == 0
    assert "<relevant-specs>" in result.stdout
    assert "Backend Specifications" in result.stdout
    assert "Development Guides" in result.stdout
    assert "Pre-Development Checklist" in result.stdout


@pytest.mark.asyncio
async def test_session_start_hook_frontend_task(test_repo, hook_script):
    """Test hook loads frontend specs for frontend task."""
    # Create task
    journal = EventJournal(test_repo / ".reins" / "journal.jsonl")
    projection = TaskContextProjection()
    manager = TaskManager(journal, projection, run_id="test")

    task_id = await manager.create_task(
        title="Frontend Task",
        task_type="frontend",
        prd_content="Frontend work",
        acceptance_criteria=["Done"],
        created_by="test",
        priority="P0",
        assignee="test-user",
    )

    # Export task
    exporter = TaskExporter(projection, test_repo / ".reins" / "tasks")
    exporter.export_task(task_id)
    exporter.set_current_task(task_id)

    # Create frontend spec
    frontend_spec_dir = test_repo / ".reins" / "spec" / "frontend"
    frontend_index = frontend_spec_dir / "index.md"
    frontend_index.write_text("""# Frontend Specifications

## Component Guidelines

- Use functional components
- Follow React best practices
""")

    # Run hook
    result = subprocess.run(
        ["python3", str(hook_script)],
        cwd=test_repo,
        capture_output=True,
        text=True,
        timeout=5,
    )

    # Should load frontend specs
    assert result.returncode == 0
    assert "Frontend Specifications" in result.stdout
    assert "Component Guidelines" in result.stdout


@pytest.mark.asyncio
async def test_session_start_hook_fullstack_task(test_repo, hook_script):
    """Test hook loads both backend and frontend specs for fullstack task."""
    # Create task
    journal = EventJournal(test_repo / ".reins" / "journal.jsonl")
    projection = TaskContextProjection()
    manager = TaskManager(journal, projection, run_id="test")

    task_id = await manager.create_task(
        title="Fullstack Task",
        task_type="fullstack",
        prd_content="Fullstack work",
        acceptance_criteria=["Done"],
        created_by="test",
        priority="P0",
        assignee="test-user",
    )

    # Export task
    exporter = TaskExporter(projection, test_repo / ".reins" / "tasks")
    exporter.export_task(task_id)
    exporter.set_current_task(task_id)

    # Create specs
    backend_spec_dir = test_repo / ".reins" / "spec" / "backend"
    backend_index = backend_spec_dir / "index.md"
    backend_index.write_text("# Backend Specifications")

    frontend_spec_dir = test_repo / ".reins" / "spec" / "frontend"
    frontend_index = frontend_spec_dir / "index.md"
    frontend_index.write_text("# Frontend Specifications")

    # Run hook
    result = subprocess.run(
        ["python3", str(hook_script)],
        cwd=test_repo,
        capture_output=True,
        text=True,
        timeout=5,
    )

    # Should load both specs
    assert result.returncode == 0
    assert "Backend Specifications" in result.stdout
    assert "Frontend Specifications" in result.stdout


@pytest.mark.asyncio
async def test_session_start_hook_timeout(test_repo, hook_script):
    """Test hook respects timeout."""
    # Create task
    journal = EventJournal(test_repo / ".reins" / "journal.jsonl")
    projection = TaskContextProjection()
    manager = TaskManager(journal, projection, run_id="test")

    task_id = await manager.create_task(
        title="Test Task",
        task_type="backend",
        prd_content="Test",
        acceptance_criteria=["Done"],
        created_by="test",
        priority="P0",
        assignee="test-user",
    )

    # Export task
    exporter = TaskExporter(projection, test_repo / ".reins" / "tasks")
    exporter.export_task(task_id)
    exporter.set_current_task(task_id)

    # Run hook with short timeout
    result = subprocess.run(
        ["python3", str(hook_script)],
        cwd=test_repo,
        capture_output=True,
        text=True,
        timeout=1,  # 1 second timeout
    )

    # Should complete within timeout
    assert result.returncode == 0


def test_session_start_hook_not_in_repo(tmp_path, hook_script):
    """Test hook gracefully handles non-Reins directory."""
    # Run hook in directory without .reins
    result = subprocess.run(
        ["python3", str(hook_script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=5,
    )

    # Should succeed with no output
    assert result.returncode == 0
    assert result.stdout == ""
