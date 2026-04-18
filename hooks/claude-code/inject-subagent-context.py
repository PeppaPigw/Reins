#!/usr/bin/env python3
"""Subagent context injection hook for Claude Code.

Injects task-specific context before spawning a subagent.
Reads agent-specific JSONL files (implement.jsonl, check.jsonl, debug.jsonl)
and injects the context as messages.

This hook is triggered before subagent spawn and provides the subagent
with accumulated context from previous interactions.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any


def find_repo_root() -> Path | None:
    """Find repository root by looking for .reins directory.

    Returns:
        Path to repository root or None if not found
    """
    current = Path.cwd()

    # Try current directory and parents
    for path in [current] + list(current.parents):
        if (path / ".reins").exists():
            return path

    return None


def load_current_task(repo_root: Path) -> str | None:
    """Load current task ID from .reins/.current-task.

    Args:
        repo_root: Repository root path

    Returns:
        Task ID or None if no current task
    """
    current_task_file = repo_root / ".reins" / ".current-task"

    if not current_task_file.exists():
        return None

    try:
        content = current_task_file.read_text().strip()
        # Format: "tasks/{task_id}"
        if content.startswith("tasks/"):
            return content.split("/")[-1]
        return None
    except Exception:
        return None


def get_agent_type() -> str | None:
    """Get agent type from environment variable.

    Returns:
        Agent type (e.g., 'implement', 'check', 'debug') or None
    """
    return os.environ.get("REINS_AGENT_TYPE")


def load_agent_context(repo_root: Path, task_id: str, agent_type: str) -> list[dict[str, Any]]:
    """Load agent-specific context from JSONL file.

    Args:
        repo_root: Repository root path
        task_id: Task ID
        agent_type: Agent type (e.g., 'implement', 'check', 'debug')

    Returns:
        List of context messages
    """
    jsonl_path = repo_root / ".reins" / "tasks" / task_id / f"{agent_type}.jsonl"

    if not jsonl_path.exists():
        return []

    messages = []
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        message = json.loads(line)
                        messages.append(message)
                    except json.JSONDecodeError:
                        # Skip invalid lines
                        continue
    except Exception:
        pass

    return messages


def format_context_output(agent_type: str, messages: list[dict[str, Any]]) -> str:
    """Format context messages for injection.

    Args:
        agent_type: Agent type
        messages: List of context messages

    Returns:
        Formatted output string
    """
    if not messages:
        return ""

    lines = []

    lines.append(f"<{agent_type}-context>")
    lines.append(f"## Context for {agent_type.capitalize()} Agent")
    lines.append("")
    lines.append(f"Accumulated context from previous {agent_type} sessions:")
    lines.append("")

    for i, message in enumerate(messages, 1):
        role = message.get("role", "unknown")
        content = message.get("content", "")
        metadata = message.get("metadata", {})

        lines.append(f"### Message {i} ({role})")
        lines.append("")

        if metadata:
            lines.append("**Metadata:**")
            for key, value in metadata.items():
                lines.append(f"- {key}: {value}")
            lines.append("")

        lines.append(content)
        lines.append("")

    lines.append(f"</{agent_type}-context>")

    return "\n".join(lines)


def main() -> int:
    """Main entry point.

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        # Find repository root
        repo_root = find_repo_root()
        if not repo_root:
            # No .reins directory found - not a Reins project
            return 0

        # Load current task
        task_id = load_current_task(repo_root)
        if not task_id:
            # No current task - nothing to inject
            return 0

        # Get agent type from environment
        agent_type = get_agent_type()
        if not agent_type:
            # No agent type specified - nothing to inject
            return 0

        # Load agent-specific context
        messages = load_agent_context(repo_root, task_id, agent_type)

        if not messages:
            # No context to inject
            return 0

        # Format and output
        output = format_context_output(agent_type, messages)
        print(output)

        return 0

    except Exception as e:
        print(f"Error in inject-subagent-context hook: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
