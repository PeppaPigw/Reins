#!/usr/bin/env python3
"""Session start hook for Claude Code.

Automatically injects task context and relevant specs at session start.
This hook reads the current task from .reins/.current-task and loads:
- Task metadata (status, PRD, acceptance criteria)
- Relevant specs based on task type and package
- Agent context from JSONL files

Output is formatted as <system-reminder> tags for Claude Code.
"""

import json
import re
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


def load_task_metadata(repo_root: Path, task_id: str) -> dict[str, Any] | None:
    """Load task metadata from task.json.

    Args:
        repo_root: Repository root path
        task_id: Task ID

    Returns:
        Task metadata dictionary or None if not found
    """
    task_json_path = repo_root / ".reins" / "tasks" / task_id / "task.json"

    if not task_json_path.exists():
        return None

    try:
        with open(task_json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_prd(repo_root: Path, task_id: str) -> str | None:
    """Load PRD content from prd.md.

    Args:
        repo_root: Repository root path
        task_id: Task ID

    Returns:
        PRD content or None if not found
    """
    prd_path = repo_root / ".reins" / "tasks" / task_id / "prd.md"

    if not prd_path.exists():
        return None

    try:
        return prd_path.read_text(encoding="utf-8")
    except Exception:
        return None


def parse_checklist(content: str) -> list[tuple[bool, str, str | None]]:
    """Parse checklist items from index.md content.

    Args:
        content: Index.md file content

    Returns:
        List of (checked, spec_file, description) tuples
    """
    items = []
    lines = content.split("\n")
    in_checklist = False

    # Regex patterns
    checklist_header = re.compile(r"^##\s+Pre-Development Checklist", re.IGNORECASE)
    checklist_item = re.compile(r"^-\s+\[([ x])\]\s+`?([^`\s]+\.md)`?(?:\s+-\s+(.+))?")

    for line in lines:
        # Check for checklist header
        if checklist_header.match(line):
            in_checklist = True
            continue

        # Check for next section (ends checklist)
        if in_checklist and line.startswith("##"):
            break

        # Parse checklist items
        if in_checklist:
            match = checklist_item.match(line)
            if match:
                checked = match.group(1).lower() == "x"
                spec_file = match.group(2)
                description = match.group(3) if match.group(3) else None
                items.append((checked, spec_file, description))

    return items


def load_relevant_specs(repo_root: Path, task_type: str) -> tuple[list[tuple[str, str]], dict[str, list[tuple[bool, str, str | None]]]]:
    """Load relevant specs based on task type.

    Args:
        repo_root: Repository root path
        task_type: Task type (e.g., 'backend', 'frontend', 'fullstack')

    Returns:
        Tuple of (specs, checklists) where:
        - specs: List of (spec_path, spec_content) tuples
        - checklists: Dict mapping layer name to list of (checked, spec_file, description) tuples
    """
    specs = []
    checklists = {}
    spec_dir = repo_root / ".reins" / "spec"

    if not spec_dir.exists():
        return specs, checklists

    # Determine which spec directories to load based on task type
    spec_dirs = []
    if task_type in ["backend", "fullstack"]:
        spec_dirs.append("backend")
    if task_type in ["frontend", "fullstack"]:
        spec_dirs.append("frontend")

    # Always include guides
    spec_dirs.append("guides")

    # Load index.md from each relevant directory and parse checklists
    for dir_name in spec_dirs:
        index_path = spec_dir / dir_name / "index.md"
        if index_path.exists():
            try:
                content = index_path.read_text(encoding="utf-8")
                specs.append((str(index_path.relative_to(repo_root)), content))

                # Parse checklist from index
                items = parse_checklist(content)
                if items:
                    checklists[dir_name] = items
            except Exception:
                pass

    return specs, checklists


def format_output(task_metadata: dict[str, Any], prd_content: str | None, specs: list[tuple[str, str]], checklists: dict[str, list[tuple[bool, str, str | None]]]) -> str:
    """Format output as system-reminder tags.

    Args:
        task_metadata: Task metadata dictionary
        prd_content: PRD content
        specs: List of (spec_path, spec_content) tuples
        checklists: Dict mapping layer name to list of (checked, spec_file, description) tuples

    Returns:
        Formatted output string
    """
    lines = []

    lines.append("<session-context>")
    lines.append("Active task context loaded from .reins/")
    lines.append("</session-context>")
    lines.append("")

    lines.append("<current-task>")
    lines.append(f"## Task: {task_metadata['title']}")
    lines.append("")
    lines.append(f"**Task ID:** {task_metadata['task_id']}")
    lines.append(f"**Type:** {task_metadata['task_type']}")
    lines.append(f"**Status:** {task_metadata['status']}")
    lines.append(f"**Priority:** {task_metadata['priority']}")
    lines.append(f"**Assignee:** {task_metadata['assignee']}")
    lines.append(f"**Branch:** {task_metadata['branch']}")
    lines.append("")

    if prd_content:
        lines.append("## PRD")
        lines.append("")
        lines.append(prd_content)
        lines.append("")

    lines.append("</current-task>")
    lines.append("")

    if specs:
        lines.append("<relevant-specs>")
        lines.append("## Relevant Specifications")
        lines.append("")
        lines.append("Read these specs before starting work:")
        lines.append("")

        for spec_path, spec_content in specs:
            lines.append(f"### {spec_path}")
            lines.append("")
            lines.append(spec_content)
            lines.append("")

        lines.append("</relevant-specs>")
        lines.append("")

    if checklists:
        lines.append("<pre-development-checklist>")
        lines.append("## Pre-Development Checklist")
        lines.append("")
        lines.append("Before starting work, ensure you have read:")
        lines.append("")

        for layer_name, items in checklists.items():
            lines.append(f"### {layer_name.capitalize()}")
            lines.append("")
            for checked, spec_file, description in items:
                check_mark = "x" if checked else " "
                if description:
                    lines.append(f"- [{check_mark}] `{spec_file}` - {description}")
                else:
                    lines.append(f"- [{check_mark}] `{spec_file}`")
            lines.append("")

        lines.append("</pre-development-checklist>")

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

        # Load task metadata
        task_metadata = load_task_metadata(repo_root, task_id)
        if not task_metadata:
            print(f"Warning: Could not load task metadata for {task_id}", file=sys.stderr)
            return 0

        # Load PRD
        prd_content = load_prd(repo_root, task_id)

        # Load relevant specs
        task_type = task_metadata.get("task_type", "backend")
        specs, checklists = load_relevant_specs(repo_root, task_type)

        # Format and output
        output = format_output(task_metadata, prd_content, specs, checklists)
        print(output)

        return 0

    except Exception as e:
        print(f"Error in session-start hook: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
