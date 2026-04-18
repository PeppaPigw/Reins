"""Tests for task context JSONL utilities."""

import pytest
from pathlib import Path

from reins.task.context_jsonl import (
    ContextJSONL,
    ContextMessage,
    add_context,
    clear_context,
    list_agent_contexts,
    read_context,
)


def test_context_message_creation():
    """Test creating a context message."""
    message = ContextMessage(
        role="user",
        content="Test message",
        metadata={"source": "test"},
    )

    assert message.role == "user"
    assert message.content == "Test message"
    assert message.metadata["source"] == "test"


def test_context_message_to_dict():
    """Test converting message to dictionary."""
    message = ContextMessage(
        role="system",
        content="System message",
        metadata={"timestamp": "2024-01-01"},
    )

    data = message.to_dict()
    assert data["role"] == "system"
    assert data["content"] == "System message"
    assert data["metadata"]["timestamp"] == "2024-01-01"


def test_context_message_from_dict():
    """Test creating message from dictionary."""
    data = {
        "role": "assistant",
        "content": "Assistant response",
        "metadata": {"agent": "implement"},
    }

    message = ContextMessage.from_dict(data)
    assert message.role == "assistant"
    assert message.content == "Assistant response"
    assert message.metadata["agent"] == "implement"


def test_context_message_json_roundtrip():
    """Test JSON serialization roundtrip."""
    original = ContextMessage(
        role="user",
        content="Test content",
        metadata={"key": "value"},
    )

    json_str = original.to_json()
    restored = ContextMessage.from_json(json_str)

    assert restored.role == original.role
    assert restored.content == original.content
    assert restored.metadata == original.metadata


def test_write_message(tmp_path):
    """Test writing a message to JSONL file."""
    file_path = tmp_path / "test.jsonl"
    message = ContextMessage(role="user", content="Test")

    ContextJSONL.write_message(file_path, message)

    assert file_path.exists()
    content = file_path.read_text()
    assert "user" in content
    assert "Test" in content


def test_write_multiple_messages(tmp_path):
    """Test writing multiple messages to JSONL file."""
    file_path = tmp_path / "test.jsonl"

    messages = [
        ContextMessage(role="user", content="Message 1"),
        ContextMessage(role="assistant", content="Message 2"),
        ContextMessage(role="user", content="Message 3"),
    ]

    for message in messages:
        ContextJSONL.write_message(file_path, message)

    lines = file_path.read_text().strip().split("\n")
    assert len(lines) == 3


def test_read_messages(tmp_path):
    """Test reading messages from JSONL file."""
    file_path = tmp_path / "test.jsonl"

    # Write messages
    messages = [
        ContextMessage(role="user", content="Message 1"),
        ContextMessage(role="assistant", content="Message 2"),
    ]

    for message in messages:
        ContextJSONL.write_message(file_path, message)

    # Read messages
    read_messages = ContextJSONL.read_messages(file_path)

    assert len(read_messages) == 2
    assert read_messages[0].role == "user"
    assert read_messages[0].content == "Message 1"
    assert read_messages[1].role == "assistant"
    assert read_messages[1].content == "Message 2"


def test_read_messages_nonexistent_file(tmp_path):
    """Test reading from nonexistent file."""
    file_path = tmp_path / "nonexistent.jsonl"
    messages = ContextJSONL.read_messages(file_path)
    assert messages == []


def test_read_messages_with_empty_lines(tmp_path):
    """Test reading messages with empty lines."""
    file_path = tmp_path / "test.jsonl"

    # Write with empty lines
    file_path.write_text(
        '{"role": "user", "content": "Message 1", "metadata": {}}\n'
        '\n'
        '{"role": "assistant", "content": "Message 2", "metadata": {}}\n'
    )

    messages = ContextJSONL.read_messages(file_path)
    assert len(messages) == 2


def test_read_messages_with_invalid_json(tmp_path):
    """Test reading messages with invalid JSON lines."""
    file_path = tmp_path / "test.jsonl"

    # Write with invalid JSON
    file_path.write_text(
        '{"role": "user", "content": "Valid", "metadata": {}}\n'
        'invalid json line\n'
        '{"role": "assistant", "content": "Also valid", "metadata": {}}\n'
    )

    messages = ContextJSONL.read_messages(file_path)
    # Should skip invalid line
    assert len(messages) == 2
    assert messages[0].content == "Valid"
    assert messages[1].content == "Also valid"


def test_clear_messages(tmp_path):
    """Test clearing messages from JSONL file."""
    file_path = tmp_path / "test.jsonl"

    # Write messages
    ContextJSONL.write_message(file_path, ContextMessage(role="user", content="Test"))
    assert file_path.exists()

    # Clear messages
    ContextJSONL.clear_messages(file_path)
    assert not file_path.exists()


def test_clear_messages_nonexistent_file(tmp_path):
    """Test clearing nonexistent file."""
    file_path = tmp_path / "nonexistent.jsonl"
    # Should not raise error
    ContextJSONL.clear_messages(file_path)


def test_validate_jsonl_valid(tmp_path):
    """Test validating valid JSONL file."""
    file_path = tmp_path / "test.jsonl"

    messages = [
        ContextMessage(role="user", content="Message 1"),
        ContextMessage(role="assistant", content="Message 2"),
    ]

    for message in messages:
        ContextJSONL.write_message(file_path, message)

    is_valid, errors = ContextJSONL.validate_jsonl(file_path)
    assert is_valid
    assert len(errors) == 0


def test_validate_jsonl_missing_role(tmp_path):
    """Test validating JSONL with missing role."""
    file_path = tmp_path / "test.jsonl"
    file_path.write_text('{"content": "Missing role", "metadata": {}}\n')

    is_valid, errors = ContextJSONL.validate_jsonl(file_path)
    assert not is_valid
    assert len(errors) == 1
    assert "missing 'role'" in errors[0]


def test_validate_jsonl_missing_content(tmp_path):
    """Test validating JSONL with missing content."""
    file_path = tmp_path / "test.jsonl"
    file_path.write_text('{"role": "user", "metadata": {}}\n')

    is_valid, errors = ContextJSONL.validate_jsonl(file_path)
    assert not is_valid
    assert len(errors) == 1
    assert "missing 'content'" in errors[0]


def test_validate_jsonl_invalid_role(tmp_path):
    """Test validating JSONL with invalid role."""
    file_path = tmp_path / "test.jsonl"
    file_path.write_text('{"role": "invalid", "content": "Test", "metadata": {}}\n')

    is_valid, errors = ContextJSONL.validate_jsonl(file_path)
    assert not is_valid
    assert len(errors) == 1
    assert "invalid role" in errors[0]


def test_validate_jsonl_invalid_json(tmp_path):
    """Test validating JSONL with invalid JSON."""
    file_path = tmp_path / "test.jsonl"
    file_path.write_text('not valid json\n')

    is_valid, errors = ContextJSONL.validate_jsonl(file_path)
    assert not is_valid
    assert len(errors) == 1
    assert "invalid JSON" in errors[0]


def test_validate_jsonl_nonexistent_file(tmp_path):
    """Test validating nonexistent file."""
    file_path = tmp_path / "nonexistent.jsonl"
    is_valid, errors = ContextJSONL.validate_jsonl(file_path)
    assert is_valid
    assert len(errors) == 0


def test_add_context(tmp_path):
    """Test add_context helper function."""
    task_dir = tmp_path / "task-1"

    add_context(task_dir, "implement", "user", "Do something", {"source": "test"})

    jsonl_file = task_dir / "implement.jsonl"
    assert jsonl_file.exists()

    messages = ContextJSONL.read_messages(jsonl_file)
    assert len(messages) == 1
    assert messages[0].role == "user"
    assert messages[0].content == "Do something"
    assert messages[0].metadata["source"] == "test"


def test_read_context(tmp_path):
    """Test read_context helper function."""
    task_dir = tmp_path / "task-1"

    # Add some messages
    add_context(task_dir, "check", "user", "Message 1")
    add_context(task_dir, "check", "assistant", "Message 2")

    # Read context
    messages = read_context(task_dir, "check")
    assert len(messages) == 2
    assert messages[0].content == "Message 1"
    assert messages[1].content == "Message 2"


def test_read_context_nonexistent(tmp_path):
    """Test reading context for nonexistent agent."""
    task_dir = tmp_path / "task-1"
    messages = read_context(task_dir, "nonexistent")
    assert messages == []


def test_clear_context(tmp_path):
    """Test clear_context helper function."""
    task_dir = tmp_path / "task-1"

    # Add messages
    add_context(task_dir, "debug", "user", "Test")
    jsonl_file = task_dir / "debug.jsonl"
    assert jsonl_file.exists()

    # Clear context
    clear_context(task_dir, "debug")
    assert not jsonl_file.exists()


def test_list_agent_contexts(tmp_path):
    """Test listing agent contexts."""
    task_dir = tmp_path / "task-1"
    task_dir.mkdir()

    # Create multiple agent contexts
    add_context(task_dir, "implement", "user", "Test 1")
    add_context(task_dir, "check", "user", "Test 2")
    add_context(task_dir, "debug", "user", "Test 3")

    agents = list_agent_contexts(task_dir)
    assert len(agents) == 3
    assert "implement" in agents
    assert "check" in agents
    assert "debug" in agents


def test_list_agent_contexts_empty(tmp_path):
    """Test listing agent contexts in empty directory."""
    task_dir = tmp_path / "task-1"
    task_dir.mkdir()

    agents = list_agent_contexts(task_dir)
    assert agents == []


def test_list_agent_contexts_nonexistent(tmp_path):
    """Test listing agent contexts in nonexistent directory."""
    task_dir = tmp_path / "nonexistent"
    agents = list_agent_contexts(task_dir)
    assert agents == []


def test_context_message_with_unicode(tmp_path):
    """Test context message with Unicode content."""
    file_path = tmp_path / "test.jsonl"

    message = ContextMessage(
        role="user",
        content="测试内容 🚀",
        metadata={"language": "中文"},
    )

    ContextJSONL.write_message(file_path, message)
    messages = ContextJSONL.read_messages(file_path)

    assert len(messages) == 1
    assert messages[0].content == "测试内容 🚀"
    assert messages[0].metadata["language"] == "中文"
