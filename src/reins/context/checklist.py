"""Spec pre-development checklist parser.

Parses Pre-Development Checklist sections from spec index.md files
and validates that all referenced spec files exist.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ChecklistItem:
    """A single item in a pre-development checklist."""

    checked: bool
    """Whether the item is checked"""

    spec_file: str
    """Spec file name (e.g., 'error-handling.md')"""

    description: str | None = None
    """Optional description of the spec"""

    def __str__(self) -> str:
        """String representation."""
        check = "x" if self.checked else " "
        if self.description:
            return f"- [{check}] {self.spec_file} - {self.description}"
        return f"- [{check}] {self.spec_file}"


@dataclass
class Checklist:
    """Pre-development checklist from a spec index.md file."""

    spec_dir: Path
    """Directory containing the specs"""

    items: list[ChecklistItem]
    """Checklist items"""

    def validate(self) -> tuple[bool, list[str]]:
        """Validate that all referenced spec files exist.

        Returns:
            Tuple of (is_valid, missing_files)
        """
        missing = []

        for item in self.items:
            spec_path = self.spec_dir / item.spec_file
            if not spec_path.exists():
                missing.append(item.spec_file)

        return len(missing) == 0, missing

    def get_required_specs(self) -> list[Path]:
        """Get paths to all required spec files.

        Returns:
            List of spec file paths
        """
        specs = []
        for item in self.items:
            spec_path = self.spec_dir / item.spec_file
            if spec_path.exists():
                specs.append(spec_path)
        return specs


class ChecklistParser:
    """Parser for Pre-Development Checklist sections in spec index.md files."""

    # Regex patterns
    CHECKLIST_HEADER = re.compile(r"^##\s+Pre-Development Checklist", re.IGNORECASE)
    CHECKLIST_ITEM = re.compile(r"^-\s+\[([ x])\]\s+`?([^`\s]+\.md)`?(?:\s+-\s+(.+))?")

    @classmethod
    def parse(cls, index_path: Path) -> Checklist | None:
        """Parse checklist from index.md file.

        Args:
            index_path: Path to index.md file

        Returns:
            Checklist or None if no checklist found
        """
        if not index_path.exists():
            return None

        try:
            content = index_path.read_text(encoding="utf-8")
        except Exception:
            return None

        return cls.parse_content(content, index_path.parent)

    @classmethod
    def parse_content(cls, content: str, spec_dir: Path) -> Checklist | None:
        """Parse checklist from content string.

        Args:
            content: Index.md content
            spec_dir: Directory containing the specs

        Returns:
            Checklist or None if no checklist found
        """
        lines = content.split("\n")
        items: list[ChecklistItem] = []
        in_checklist = False

        for line in lines:
            # Check for checklist header
            if cls.CHECKLIST_HEADER.match(line):
                in_checklist = True
                continue

            # Check for next section (ends checklist)
            if in_checklist and line.startswith("##"):
                break

            # Parse checklist items
            if in_checklist:
                match = cls.CHECKLIST_ITEM.match(line)
                if match:
                    checked = match.group(1).lower() == "x"
                    spec_file = match.group(2)
                    description = match.group(3) if match.group(3) else None

                    items.append(
                        ChecklistItem(
                            checked=checked,
                            spec_file=spec_file,
                            description=description,
                        )
                    )

        if not items:
            return None

        return Checklist(spec_dir=spec_dir, items=items)

    @classmethod
    def find_checklists(cls, spec_root: Path) -> dict[str, Checklist]:
        """Find all checklists in spec directory structure.

        Args:
            spec_root: Root spec directory (e.g., .reins/spec/)

        Returns:
            Dictionary mapping layer name to checklist
        """
        checklists: dict[str, Checklist] = {}

        if not spec_root.exists():
            return checklists

        # Look for index.md in each subdirectory
        for layer_dir in spec_root.iterdir():
            if not layer_dir.is_dir():
                continue

            index_path = layer_dir / "index.md"
            if index_path.exists():
                checklist = cls.parse(index_path)
                if checklist:
                    checklists[layer_dir.name] = checklist

        return checklists


def create_checklist_template(layer_name: str, spec_files: list[str]) -> str:
    """Create a checklist template for a spec layer.

    Args:
        layer_name: Name of the spec layer (e.g., 'backend', 'frontend')
        description: Description of the layer

    Returns:
        Markdown content with checklist template
    """
    lines = [
        f"# {layer_name.capitalize()} Specifications\n",
        "\n",
        "## Pre-Development Checklist\n",
        "\n",
        f"Before starting {layer_name} work, read:\n",
        "\n",
    ]

    for spec_file in spec_files:
        lines.append(f"- [ ] `{spec_file}`\n")

    lines.append("\n")
    lines.append("---\n")
    lines.append("\n")

    return "".join(lines)
