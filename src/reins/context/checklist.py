"""Spec pre-development checklist parsing and validation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

from reins.context.types import SpecLayer

_CHECKLIST_HEADER = re.compile(r"^##\s+Pre-Development Checklist\b", re.IGNORECASE)
_CHECKLIST_ITEM = re.compile(r"^(?P<indent>\s*)-\s+\[(?P<checked>[ xX])\]\s+(?P<body>.+?)\s*$")
_MARKDOWN_LINK = re.compile(
    r"^\[(?P<label>[^\]]+)\]\((?P<target>[^)]+)\)(?:\s*(?:-|--)\s*(?P<description>.+))?$"
)
_CODE_TARGET = re.compile(
    r"^`?(?P<target>[^`\s]+(?:\.[A-Za-z0-9._-]+)?)`?(?:\s*(?:-|--)\s*(?P<description>.+))?$"
)


def _normalize_relative_path(value: str) -> str:
    return value.replace("\\", "/").lstrip("./")


@dataclass
class ChecklistItem:
    """A single item in a pre-development checklist."""

    checked: bool
    text: str | None = None
    target: str | None = None
    spec_file: str | None = None
    description: str | None = None
    level: int = 0
    children: list["ChecklistItem"] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.target is None and self.spec_file is not None:
            self.target = self.spec_file
        if self.spec_file is None and self.target is not None:
            self.spec_file = self.target
        if self.text is None:
            self.text = self.target or ""

    def resolved_path(self, spec_dir: Path) -> Path | None:
        """Resolve the item's target relative to the checklist directory."""
        if self.target is None:
            return None
        return (spec_dir / self.target).resolve()

    def to_display(self, spec_dir: Path | None = None) -> str:
        """Return a human-readable label for the checklist item."""
        target = self.target
        if target and spec_dir is not None:
            target = _normalize_relative_path(str((spec_dir / target).resolve()))
        base = target or self.text or ""
        if self.description:
            return f"{base} - {self.description}"
        return base

    def __str__(self) -> str:
        """Render the item using the original checklist bullet form."""
        check = "x" if self.checked else " "
        base = self.target or self.text or ""
        if self.description:
            return f"- [{check}] {base} - {self.description}"
        return f"- [{check}] {base}"


@dataclass(frozen=True)
class ChecklistValidation:
    """Validation result for checklist completion and target existence."""

    is_complete: bool
    missing_files: list[str]
    incomplete_items: list[str]
    completed_items: list[str]
    total_items: int
    completed_count: int


@dataclass(frozen=True)
class LayerValidation:
    """Validation result for a layer directory tree."""

    required_layers: list[str]
    present_layers: list[str]
    missing_layers: list[str]
    custom_layers: list[str]

    @property
    def is_valid(self) -> bool:
        """Return ``True`` when all required layers are present."""
        return not self.missing_layers


@dataclass
class Checklist:
    """Pre-development checklist from a spec ``index.md`` file."""

    spec_dir: Path
    items: list[ChecklistItem]
    source_path: Path | None = None
    layer: SpecLayer | None = None

    def iter_items(self) -> Iterator[ChecklistItem]:
        """Iterate over all checklist items, including nested items."""
        for item in self.items:
            yield item
            yield from self._iter_children(item.children)

    def _iter_children(self, items: list[ChecklistItem]) -> Iterator[ChecklistItem]:
        for item in items:
            yield item
            yield from self._iter_children(item.children)

    def validate(self) -> tuple[bool, list[str]]:
        """Validate that all referenced target files exist."""
        missing = [
            item.target
            for item in self.iter_items()
            if item.target is not None and not (self.spec_dir / item.target).exists()
        ]
        normalized = [_normalize_relative_path(path) for path in missing if path]
        return len(normalized) == 0, normalized

    def validate_completion(self, read_specs: Iterable[str | Path] = ()) -> ChecklistValidation:
        """Validate completion against the current set of read spec files."""
        normalized_reads = {
            _normalize_relative_path(path.as_posix() if isinstance(path, Path) else str(path))
            for path in read_specs
        }

        missing_files: list[str] = []
        incomplete_items: list[str] = []
        completed_items: list[str] = []

        for item in self.iter_items():
            relative_target = (
                _normalize_relative_path(item.target) if item.target is not None else None
            )
            if relative_target is not None and not (self.spec_dir / relative_target).exists():
                missing_files.append(relative_target)

            completed = self._is_item_completed(item, normalized_reads)
            display = item.to_display()
            if completed:
                completed_items.append(display)
            else:
                incomplete_items.append(display)

        return ChecklistValidation(
            is_complete=not missing_files and not incomplete_items,
            missing_files=missing_files,
            incomplete_items=incomplete_items,
            completed_items=completed_items,
            total_items=len(completed_items) + len(incomplete_items),
            completed_count=len(completed_items),
        )

    def _is_item_completed(self, item: ChecklistItem, read_specs: set[str]) -> bool:
        if item.checked:
            return True

        relative_target = _normalize_relative_path(item.target) if item.target else None
        if relative_target is not None and relative_target in read_specs:
            return True

        if item.children:
            return all(self._is_item_completed(child, read_specs) for child in item.children)

        return False

    def get_required_specs(self) -> list[Path]:
        """Return all existing files referenced by checklist items."""
        specs: list[Path] = []
        for item in self.iter_items():
            if item.target is None:
                continue
            spec_path = self.spec_dir / item.target
            if spec_path.exists():
                specs.append(spec_path)
        return specs


class ChecklistParser:
    """Parser for checklist sections in spec ``index.md`` files."""

    @classmethod
    def parse(cls, index_path: Path) -> Checklist | None:
        """Parse a checklist from an ``index.md`` file."""
        if not index_path.exists():
            return None
        try:
            content = index_path.read_text(encoding="utf-8")
        except OSError:
            return None
        return cls.parse_content(content, index_path.parent, source_path=index_path)

    @classmethod
    def parse_content(
        cls,
        content: str,
        spec_dir: Path,
        *,
        source_path: Path | None = None,
    ) -> Checklist | None:
        """Parse a checklist section from raw markdown content."""
        items: list[ChecklistItem] = []
        stack: list[tuple[int, ChecklistItem]] = []
        in_checklist = False

        for line in content.splitlines():
            if _CHECKLIST_HEADER.match(line):
                in_checklist = True
                continue

            if in_checklist and line.startswith("##"):
                break

            if not in_checklist:
                continue

            match = _CHECKLIST_ITEM.match(line)
            if not match:
                continue

            indent = len(match.group("indent").expandtabs(2))
            level = indent // 2
            checked = match.group("checked").lower() == "x"
            body = match.group("body").strip()
            text, target, description = cls._parse_body(body)
            item = ChecklistItem(
                checked=checked,
                text=text,
                target=target,
                description=description,
                level=level,
            )

            while stack and stack[-1][0] >= level:
                stack.pop()

            if stack:
                stack[-1][1].children.append(item)
            else:
                items.append(item)
            stack.append((level, item))

        if not items:
            return None

        layer = SpecLayer.from_name(spec_dir.name)
        return Checklist(spec_dir=spec_dir, items=items, source_path=source_path, layer=layer)

    @classmethod
    def _parse_body(cls, body: str) -> tuple[str, str | None, str | None]:
        link_match = _MARKDOWN_LINK.match(body)
        if link_match:
            label = link_match.group("label").strip()
            target = _normalize_relative_path(link_match.group("target").strip())
            description = link_match.group("description")
            return label, target, description.strip() if description else None

        target_match = _CODE_TARGET.match(body)
        if target_match:
            target = _normalize_relative_path(target_match.group("target").strip())
            description = target_match.group("description")
            return target, target, description.strip() if description else None

        return body, None, None

    @classmethod
    def find_checklists(cls, spec_root: Path) -> dict[str, Checklist]:
        """Find all checklists within a spec directory tree."""
        checklists: dict[str, Checklist] = {}
        if not spec_root.exists():
            return checklists

        for index_path in sorted(spec_root.rglob("index.md")):
            checklist = cls.parse(index_path)
            if checklist is None:
                continue
            key = index_path.parent.relative_to(spec_root).as_posix()
            checklists[key] = checklist
        return checklists


def validate_layer_structure(
    spec_root: Path,
    required_layers: Iterable[SpecLayer],
) -> LayerValidation:
    """Validate that required layer directories exist beneath ``spec_root``."""
    required = [layer.value for layer in required_layers]
    present = sorted(
        child.name
        for child in spec_root.iterdir()
        if child.is_dir() and not child.name.startswith(".")
    ) if spec_root.exists() else []
    missing = [layer for layer in required if layer not in present]
    custom = sorted(
        layer_name
        for layer_name in present
        if SpecLayer.from_name(layer_name) == SpecLayer.CUSTOM
    )
    return LayerValidation(
        required_layers=required,
        present_layers=present,
        missing_layers=missing,
        custom_layers=custom,
    )


def create_checklist_template(
    layer_name: str,
    spec_files: list[str],
) -> str:
    """Create a checklist-backed markdown ``index.md`` template."""
    title = layer_name.replace("-", " ").title()
    lines = [
        f"# {title} Specifications",
        "",
        "## Pre-Development Checklist",
        "",
        f"Before starting {layer_name} work, read:",
        "",
    ]

    if spec_files:
        for spec_file in spec_files:
            lines.append(f"- [ ] `{spec_file}`")
    else:
        lines.append("- [ ] Add checklist items for this layer before relying on it")

    lines.extend(
        [
            "",
            "## Files in This Layer",
            "",
        ]
    )

    if spec_files:
        for spec_file in spec_files:
            label = Path(spec_file).stem.replace("-", " ").title()
            lines.append(f"- [{label}]({spec_file}) - Layer-specific guidance")
    else:
        lines.append("- Add specs to this layer as the project evolves")

    return "\n".join(lines) + "\n"
