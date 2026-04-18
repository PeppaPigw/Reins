#!/usr/bin/env python3
"""Subagent context injection hook for Claude Code."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def find_repo_root() -> Path | None:
    current = Path.cwd()
    for path in [current, *current.parents]:
        if (path / ".reins").exists():
            return path
    return None


def load_current_task(repo_root: Path) -> str | None:
    current_task_file = repo_root / ".reins" / ".current-task"
    if not current_task_file.exists():
        return None
    try:
        content = current_task_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if content.startswith("tasks/"):
        return content.split("/")[-1]
    if content.startswith(".reins/tasks/") or content.startswith(".trellis/tasks/"):
        return content.split("/")[-1]
    return None


def get_agent_type() -> str | None:
    return os.environ.get("REINS_AGENT_TYPE")


def load_agent_context(repo_root: Path, task_id: str, agent_type: str) -> list[dict[str, Any]]:
    jsonl_path = repo_root / ".reins" / "tasks" / task_id / f"{agent_type}.jsonl"
    if not jsonl_path.exists():
        return []

    messages: list[dict[str, Any]] = []
    try:
        with open(jsonl_path, "r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    messages.append(json.loads(stripped))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return messages


def format_context_output(agent_type: str, messages: list[dict[str, Any]]) -> str:
    if not messages:
        return ""

    lines = [
        f"<{agent_type}-context>",
        f"## Context for {agent_type.capitalize()} Agent",
        "",
        f"Accumulated context from previous {agent_type} sessions:",
        "",
    ]

    for index, message in enumerate(messages, start=1):
        role = message.get("role", "unknown")
        content = message.get("content", "")
        metadata = message.get("metadata", {})

        lines.append(f"### Message {index} ({role})")
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
    try:
        repo_root = find_repo_root()
        if not repo_root:
            return 0

        task_id = load_current_task(repo_root)
        if not task_id:
            return 0

        agent_type = get_agent_type()
        if not agent_type:
            return 0

        messages = load_agent_context(repo_root, task_id, agent_type)
        if not messages:
            return 0

        print(format_context_output(agent_type, messages))
        return 0
    except Exception as exc:
        print(f"Error in inject-subagent-context hook: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
