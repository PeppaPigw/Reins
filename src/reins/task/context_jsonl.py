"""Task context JSONL format utilities.

JSONL (JSON Lines) format for storing task context messages.
Each line is a complete JSON object representing a message.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ContextMessage:
    """A single message in task context.

    Messages are stored in JSONL format (one JSON object per line).
    """

    role: str
    """Message role: 'system', 'user', 'assistant'"""

    content: str
    """Message content"""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Optional metadata (source, timestamp, agent, etc.)"""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "role": self.role,
            "content": self.content,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContextMessage:
        """Create from dictionary."""
        return cls(
            role=data["role"],
            content=data["content"],
            metadata=data.get("metadata", {}),
        )

    def to_json(self) -> str:
        """Convert to JSON string (single line)."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> ContextMessage:
        """Create from JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)


class ContextJSONL:
    """Utilities for reading and writing JSONL context files."""

    @staticmethod
    def write_message(file_path: Path, message: ContextMessage) -> None:
        """Append a message to JSONL file.

        Args:
            file_path: Path to JSONL file
            message: Message to append
        """
        # Ensure parent directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Append message as single line
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(message.to_json() + "\n")

    @staticmethod
    def read_messages(file_path: Path) -> list[ContextMessage]:
        """Read all messages from JSONL file.

        Args:
            file_path: Path to JSONL file

        Returns:
            List of messages
        """
        if not file_path.exists():
            return []

        messages: list[ContextMessage] = []
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:  # Skip empty lines
                    try:
                        message = ContextMessage.from_json(line)
                        messages.append(message)
                    except json.JSONDecodeError:
                        # Skip invalid lines
                        continue

        return messages

    @staticmethod
    def clear_messages(file_path: Path) -> None:
        """Clear all messages from JSONL file.

        Args:
            file_path: Path to JSONL file
        """
        if file_path.exists():
            file_path.unlink()

    @staticmethod
    def validate_jsonl(file_path: Path) -> tuple[bool, list[str]]:
        """Validate JSONL file format.

        Args:
            file_path: Path to JSONL file

        Returns:
            Tuple of (is_valid, error_messages)
        """
        if not file_path.exists():
            return True, []

        errors: list[str] = []
        line_num = 0

        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line_num += 1
                line = line.strip()

                if not line:  # Empty lines are OK
                    continue

                try:
                    data = json.loads(line)

                    # Validate required fields
                    if "role" not in data:
                        errors.append(f"Line {line_num}: missing 'role' field")
                    if "content" not in data:
                        errors.append(f"Line {line_num}: missing 'content' field")

                    # Validate role
                    if "role" in data and data["role"] not in [
                        "system",
                        "user",
                        "assistant",
                    ]:
                        errors.append(
                            f"Line {line_num}: invalid role '{data['role']}'"
                        )

                except json.JSONDecodeError as e:
                    errors.append(f"Line {line_num}: invalid JSON - {e}")

        return len(errors) == 0, errors


def add_context(
    task_dir: Path, agent: str, role: str, content: str, metadata: dict[str, Any] | None = None
) -> None:
    """Add a message to agent's context file.

    Args:
        task_dir: Task directory path
        agent: Agent name (e.g., 'implement', 'check', 'debug')
        role: Message role ('system', 'user', 'assistant')
        content: Message content
        metadata: Optional metadata
    """
    jsonl_file = task_dir / f"{agent}.jsonl"
    message = ContextMessage(
        role=role, content=content, metadata=metadata or {}
    )
    ContextJSONL.write_message(jsonl_file, message)


def read_context(task_dir: Path, agent: str) -> list[ContextMessage]:
    """Read all messages from agent's context file.

    Args:
        task_dir: Task directory path
        agent: Agent name (e.g., 'implement', 'check', 'debug')

    Returns:
        List of messages
    """
    jsonl_file = task_dir / f"{agent}.jsonl"
    return ContextJSONL.read_messages(jsonl_file)


def clear_context(task_dir: Path, agent: str) -> None:
    """Clear all messages from agent's context file.

    Args:
        task_dir: Task directory path
        agent: Agent name (e.g., 'implement', 'check', 'debug')
    """
    jsonl_file = task_dir / f"{agent}.jsonl"
    ContextJSONL.clear_messages(jsonl_file)


def list_agent_contexts(task_dir: Path) -> list[str]:
    """List all agent context files in task directory.

    Args:
        task_dir: Task directory path

    Returns:
        List of agent names (without .jsonl extension)
    """
    if not task_dir.exists():
        return []

    agents: list[str] = []
    for file_path in task_dir.glob("*.jsonl"):
        agents.append(file_path.stem)

    return sorted(agents)
