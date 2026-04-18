"""Integration tests for inject-subagent-context hook."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from reins.export import TaskExporter
from reins.kernel.event.journal import EventJournal
from reins.task.context_jsonl import add_context
from reins.task.manager import TaskManager
from reins.task.projection import TaskContextProjection


@pytest.fixture
def test_repo(tmp_path):
    """Create a test repository structure."""
    # Create .reins directory structure
    reins_dir = tmp_path / ".reins"
    reins_dir.mkdir()

    (reins_dir / "tasks").mkdir()

    return tmp_path


@pytest.fixture
def hook_script():
    """Get path to inject-subagent-context hook script."""
    hook_path = Path(__file__).parent.parent.parent / "hooks" / "claude-code" / "inject-subagent-context.py"
    if not hook_path.exists():
        pytest.skip(f"Hook script not found at {hook_path}")
    return hook_path


@pytest.mark.asyncio
async def test_inject_subagent_context_no_current_task(test_repo, hook_script):
    """Test hook when no current task is set."""
    env = os.environ.copy()
    env["REINS_AGENT_TYPE"] = "implement"

    result = subprocess.run(
        ["python3", str(hook_script)],
        cwd=test_repo,
        capture_output=True,
        text=True,
        timeout=5,
        env=env,
    )

    # Should succeed with no output (no current task)
    assert result.returncode == 0
    assert result.stdout == ""


@pytest.mark.asyncio
async def test_inject_subagent_context_no_agent_type(test_repo, hook_script):
    """Test hook when no agent type is specified."""
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

    # Run hook without agent type
    result = subprocess.run(
        ["python3", str(hook_script)],
        cwd=test_repo,
        capture_output=True,
        text=True,
        timeout=5,
    )

    # Should succeed with no output (no agent type)
    assert result.returncode == 0
    assert result.stdout == ""


@pytest.mark.asyncio
async def test_inject_subagent_context_no_context_file(test_repo, hook_script):
    """Test hook when no context file exists."""
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

    # Run hook with agent type but no context file
    env = os.environ.copy()
    env["REINS_AGENT_TYPE"] = "implement"

    result = subprocess.run(
        ["python3", str(hook_script)],
        cwd=test_repo,
        capture_output=True,
        text=True,
        timeout=5,
        env=env,
    )

    # Should succeed with no output (no context file)
    assert result.returncode == 0
    assert result.stdout == ""


@pytest.mark.asyncio
async def test_inject_subagent_context_with_messages(test_repo, hook_script):
    """Test hook injects context messages."""
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
    task_dir = exporter.export_task(task_id)
    exporter.set_current_task(task_id)

    # Add context messages
    add_context(task_dir, "implement", "system", "You are implementing a feature", {"source": "prd"})
    add_context(task_dir, "implement", "user", "Please implement the login function", {"priority": "high"})
    add_context(task_dir, "implement", "assistant", "I will implement the login function", {})

    # Run hook
    env = os.environ.copy()
    env["REINS_AGENT_TYPE"] = "implement"

    result = subprocess.run(
        ["python3", str(hook_script)],
        cwd=test_repo,
        capture_output=True,
        text=True,
        timeout=5,
        env=env,
    )

    # Should succeed with context output
    assert result.returncode == 0
    assert result.stdout != ""

    # Check output contains expected elements
    assert "<implement-context>" in result.stdout
    assert "</implement-context>" in result.stdout
    assert "Context for Implement Agent" in result.stdout
    assert "You are implementing a feature" in result.stdout
    assert "Please implement the login function" in result.stdout
    assert "I will implement the login function" in result.stdout
    assert "Message 1 (system)" in result.stdout
    assert "Message 2 (user)" in result.stdout
    assert "Message 3 (assistant)" in result.stdout


@pytest.mark.asyncio
async def test_inject_subagent_context_with_metadata(test_repo, hook_script):
    """Test hook includes metadata in output."""
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
    task_dir = exporter.export_task(task_id)
    exporter.set_current_task(task_id)

    # Add context with metadata
    add_context(
        task_dir,
        "check",
        "user",
        "Review the code for security issues",
        {"source": "security-review", "severity": "critical"}
    )

    # Run hook
    env = os.environ.copy()
    env["REINS_AGENT_TYPE"] = "check"

    result = subprocess.run(
        ["python3", str(hook_script)],
        cwd=test_repo,
        capture_output=True,
        text=True,
        timeout=5,
        env=env,
    )

    # Should include metadata
    assert result.returncode == 0
    assert "**Metadata:**" in result.stdout
    assert "source: security-review" in result.stdout
    assert "severity: critical" in result.stdout


@pytest.mark.asyncio
async def test_inject_subagent_context_different_agents(test_repo, hook_script):
    """Test hook loads correct context for different agent types."""
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
    task_dir = exporter.export_task(task_id)
    exporter.set_current_task(task_id)

    # Add context for different agents
    add_context(task_dir, "implement", "user", "Implement feature X")
    add_context(task_dir, "check", "user", "Check feature X")
    add_context(task_dir, "debug", "user", "Debug feature X")

    # Test implement agent
    env = os.environ.copy()
    env["REINS_AGENT_TYPE"] = "implement"

    result = subprocess.run(
        ["python3", str(hook_script)],
        cwd=test_repo,
        capture_output=True,
        text=True,
        timeout=5,
        env=env,
    )

    assert result.returncode == 0
    assert "Implement feature X" in result.stdout
    assert "Check feature X" not in result.stdout
    assert "Debug feature X" not in result.stdout

    # Test check agent
    env["REINS_AGENT_TYPE"] = "check"

    result = subprocess.run(
        ["python3", str(hook_script)],
        cwd=test_repo,
        capture_output=True,
        text=True,
        timeout=5,
        env=env,
    )

    assert result.returncode == 0
    assert "Check feature X" in result.stdout
    assert "Implement feature X" not in result.stdout
    assert "Debug feature X" not in result.stdout

    # Test debug agent
    env["REINS_AGENT_TYPE"] = "debug"

    result = subprocess.run(
        ["python3", str(hook_script)],
        cwd=test_repo,
        capture_output=True,
        text=True,
        timeout=5,
        env=env,
    )

    assert result.returncode == 0
    assert "Debug feature X" in result.stdout
    assert "Implement feature X" not in result.stdout
    assert "Check feature X" not in result.stdout


@pytest.mark.asyncio
async def test_inject_subagent_context_invalid_json(test_repo, hook_script):
    """Test hook handles invalid JSON gracefully."""
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
    task_dir = exporter.export_task(task_id)
    exporter.set_current_task(task_id)

    # Add valid and invalid JSON
    jsonl_file = task_dir / "implement.jsonl"
    jsonl_file.write_text(
        '{"role": "user", "content": "Valid message", "metadata": {}}\n'
        'invalid json line\n'
        '{"role": "assistant", "content": "Another valid message", "metadata": {}}\n'
    )

    # Run hook
    env = os.environ.copy()
    env["REINS_AGENT_TYPE"] = "implement"

    result = subprocess.run(
        ["python3", str(hook_script)],
        cwd=test_repo,
        capture_output=True,
        text=True,
        timeout=5,
        env=env,
    )

    # Should succeed and skip invalid line
    assert result.returncode == 0
    assert "Valid message" in result.stdout
    assert "Another valid message" in result.stdout
    assert "invalid json line" not in result.stdout


def test_inject_subagent_context_not_in_repo(tmp_path, hook_script):
    """Test hook gracefully handles non-Reins directory."""
    env = os.environ.copy()
    env["REINS_AGENT_TYPE"] = "implement"

    result = subprocess.run(
        ["python3", str(hook_script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=5,
        env=env,
    )

    # Should succeed with no output
    assert result.returncode == 0
    assert result.stdout == ""
