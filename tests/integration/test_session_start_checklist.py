"""Integration tests for session-start hook with checklist support."""

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
    hook_path = Path(__file__).parent.parent.parent / "hooks" / "claude-code" / "session-start.py"
    if not hook_path.exists():
        pytest.skip(f"Hook script not found at {hook_path}")
    return hook_path


@pytest.mark.asyncio
async def test_session_start_with_checklist(test_repo, hook_script):
    """Test hook includes checklist when present in spec index."""
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

    # Create backend spec with checklist
    backend_spec_dir = test_repo / ".reins" / "spec" / "backend"
    backend_index = backend_spec_dir / "index.md"
    backend_index.write_text("""# Backend Specifications

## Pre-Development Checklist

Before starting backend work, read:

- [ ] `error-handling.md` - Error handling patterns
- [x] `conventions.md` - Code style
- [ ] `api-design.md`
""")

    # Create guides spec with checklist
    guides_spec_dir = test_repo / ".reins" / "spec" / "guides"
    guides_index = guides_spec_dir / "index.md"
    guides_index.write_text("""# Development Guides

## Pre-Development Checklist

- [ ] `architecture.md` - System architecture
""")

    # Run hook
    result = subprocess.run(
        ["python3", str(hook_script)],
        cwd=test_repo,
        capture_output=True,
        text=True,
        timeout=5,
    )

    # Should succeed with checklist
    assert result.returncode == 0
    assert "<pre-development-checklist>" in result.stdout
    assert "</pre-development-checklist>" in result.stdout
    assert "## Pre-Development Checklist" in result.stdout
    assert "Before starting work, ensure you have read:" in result.stdout

    # Check backend checklist items
    assert "### Backend" in result.stdout
    assert "- [ ] `error-handling.md` - Error handling patterns" in result.stdout
    assert "- [x] `conventions.md` - Code style" in result.stdout
    assert "- [ ] `api-design.md`" in result.stdout

    # Check guides checklist items
    assert "### Guides" in result.stdout
    assert "- [ ] `architecture.md` - System architecture" in result.stdout


@pytest.mark.asyncio
async def test_session_start_no_checklist(test_repo, hook_script):
    """Test hook works when no checklist is present."""
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

    # Create backend spec WITHOUT checklist
    backend_spec_dir = test_repo / ".reins" / "spec" / "backend"
    backend_index = backend_spec_dir / "index.md"
    backend_index.write_text("""# Backend Specifications

## Overview

Some content without a checklist.
""")

    # Run hook
    result = subprocess.run(
        ["python3", str(hook_script)],
        cwd=test_repo,
        capture_output=True,
        text=True,
        timeout=5,
    )

    # Should succeed without checklist section
    assert result.returncode == 0
    assert "<pre-development-checklist>" not in result.stdout
    assert "<relevant-specs>" in result.stdout


@pytest.mark.asyncio
async def test_session_start_fullstack_checklist(test_repo, hook_script):
    """Test hook includes both backend and frontend checklists for fullstack task."""
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

    # Create backend spec with checklist
    backend_spec_dir = test_repo / ".reins" / "spec" / "backend"
    backend_index = backend_spec_dir / "index.md"
    backend_index.write_text("""# Backend Specifications

## Pre-Development Checklist

- [ ] `error-handling.md`
""")

    # Create frontend spec with checklist
    frontend_spec_dir = test_repo / ".reins" / "spec" / "frontend"
    frontend_index = frontend_spec_dir / "index.md"
    frontend_index.write_text("""# Frontend Specifications

## Pre-Development Checklist

- [ ] `component-patterns.md`
""")

    # Run hook
    result = subprocess.run(
        ["python3", str(hook_script)],
        cwd=test_repo,
        capture_output=True,
        text=True,
        timeout=5,
    )

    # Should include both checklists
    assert result.returncode == 0
    assert "### Backend" in result.stdout
    assert "`error-handling.md`" in result.stdout
    assert "### Frontend" in result.stdout
    assert "`component-patterns.md`" in result.stdout
