#!/usr/bin/env python3
"""Session start hook for Claude Code."""

from __future__ import annotations

import json
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


def load_task_metadata(repo_root: Path, task_id: str) -> dict[str, Any] | None:
    path = repo_root / ".reins" / "tasks" / task_id / "task.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_prd(repo_root: Path, task_id: str) -> str | None:
    path = repo_root / ".reins" / "tasks" / task_id / "prd.md"
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _bootstrap_imports(repo_root: Path) -> None:
    candidates = [
        repo_root / "src",
        Path(__file__).resolve().parents[2] / "src",
    ]
    for src_path in candidates:
        if src_path.exists():
            sys.path.insert(0, str(src_path))


def _relative_reads(repo_root: Path, checklist: Any, read_specs: set[str]) -> set[str]:
    spec_root = (repo_root / ".reins" / "spec").resolve()
    checklist_root = checklist.spec_dir.resolve()
    relative: set[str] = set()
    for read_spec in read_specs:
        path = (spec_root / read_spec).resolve()
        if path.is_relative_to(checklist_root):
            relative.add(path.relative_to(checklist_root).as_posix())
    return relative


def _requested_layers(task_type: str) -> list[str]:
    normalized = task_type.strip().lower()
    if normalized == "fullstack":
        return ["backend", "frontend"]
    if normalized in {"backend", "frontend", "unit-test", "integration-test"}:
        return [normalized]
    return ["backend"]


def _resolve_spec_sources(
    repo_root: Path,
    task_metadata: dict[str, Any],
) -> list[tuple[Path, dict[str, Any]]]:
    spec_root = repo_root / ".reins" / "spec"
    metadata = task_metadata.get("metadata", {})
    package = metadata.get("package") if isinstance(metadata, dict) else None
    task_type = task_metadata.get("task_type", "backend")
    if not isinstance(task_type, str):
        task_type = "backend"
    if not isinstance(package, str):
        package = None

    sources: list[tuple[Path, dict[str, Any]]] = []
    seen: set[Path] = set()

    def add_source(path: Path, layer: str, *, package_name: str | None, package_specific: bool) -> None:
        resolved = path.resolve()
        if resolved in seen or not path.exists():
            return
        seen.add(resolved)
        sources.append(
            (
                path,
                {
                    "layer": layer,
                    "package": package_name,
                    "package_specific": package_specific,
                },
            )
        )

    requested_layers = _requested_layers(task_type)

    if package:
        package_root = spec_root / package
        if package_root.exists():
            matched_standard = False
            for layer in requested_layers:
                layer_dir = package_root / layer
                if layer_dir.exists():
                    matched_standard = True
                    add_source(layer_dir, layer, package_name=package, package_specific=True)
            package_guides = package_root / "guides"
            if package_guides.exists():
                add_source(package_guides, "guides", package_name=package, package_specific=True)
            if not matched_standard:
                if (package_root / "index.md").exists():
                    add_source(package_root, "custom", package_name=package, package_specific=True)
                for child in sorted(package_root.iterdir()):
                    if child.is_dir() and not child.name.startswith("."):
                        add_source(child, child.name, package_name=package, package_specific=True)

    for layer in requested_layers:
        add_source(spec_root / layer, layer, package_name=None, package_specific=False)
    add_source(spec_root / "guides", "guides", package_name=None, package_specific=False)
    return sources


def load_relevant_specs(
    repo_root: Path,
    task_metadata: dict[str, Any],
) -> tuple[list[tuple[str, str]], dict[str, list[tuple[int, bool, str, str | None]]]]:
    from reins.context.checklist import ChecklistParser
    metadata = task_metadata.get("metadata", {})

    checklist_state = metadata.get("checklist", {}) if isinstance(metadata, dict) else {}
    read_specs = checklist_state.get("read_specs", []) if isinstance(checklist_state, dict) else []
    normalized_reads = {item for item in read_specs if isinstance(item, str)}

    sources = _resolve_spec_sources(repo_root, task_metadata)
    specs: list[tuple[str, str]] = []
    checklists: dict[str, list[tuple[int, bool, str, str | None]]] = {}

    for source_path, source_metadata in sources:
        index_path = source_path / "index.md" if source_path.is_dir() else source_path
        if not index_path.exists():
            continue
        try:
            content = index_path.read_text(encoding="utf-8")
        except OSError:
            continue

        specs.append((str(index_path.relative_to(repo_root)), content))

        checklist = ChecklistParser.parse(index_path)
        if checklist is None:
            continue
        relative_reads = _relative_reads(repo_root, checklist, normalized_reads)
        layer = str(source_metadata.get("layer", index_path.parent.name)).replace("-", " ").title()
        package_name = source_metadata.get("package")
        header = (
            f"{package_name.title()} / {layer}"
            if source_metadata.get("package_specific") and isinstance(package_name, str)
            else layer
        )
        checklists[header] = [
            (
                item.level,
                checklist._is_item_completed(item, relative_reads),
                item.target or item.text,
                item.description,
            )
            for item in checklist.iter_items()
        ]

    return specs, checklists


def format_output(
    task_metadata: dict[str, Any],
    prd_content: str | None,
    specs: list[tuple[str, str]],
    checklists: dict[str, list[tuple[int, bool, str, str | None]]],
) -> str:
    lines: list[str] = []
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
            lines.append(f"### {layer_name}")
            lines.append("")
            for level, complete, spec_file, description in items:
                check_mark = "x" if complete else " "
                indent = "  " * level
                if description:
                    lines.append(f"{indent}- [{check_mark}] `{spec_file}` - {description}")
                else:
                    lines.append(f"{indent}- [{check_mark}] `{spec_file}`")
            lines.append("")
        lines.append("</pre-development-checklist>")

    return "\n".join(lines)


def main() -> int:
    repo_root = find_repo_root()
    if not repo_root:
        return 0

    _bootstrap_imports(repo_root)
    task_id = load_current_task(repo_root)
    if not task_id:
        return 0

    task_metadata = load_task_metadata(repo_root, task_id)
    if not task_metadata:
        print(f"Warning: Could not load task metadata for {task_id}", file=sys.stderr)
        return 0

    prd_content = load_prd(repo_root, task_id)
    specs, checklists = load_relevant_specs(repo_root, task_metadata)
    print(format_output(task_metadata, prd_content, specs, checklists))
    return 0


if __name__ == "__main__":
    sys.exit(main())
