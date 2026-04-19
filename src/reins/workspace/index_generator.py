from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from reins.workspace.journal import DeveloperJournal


@dataclass(frozen=True)
class DeveloperStats:
    """Summary row for the global workspace index."""

    name: str
    last_active: datetime | None
    sessions: int
    commits: int
    active_file: str
    journal_files: int


class WorkspaceIndexGenerator:
    """Generate the global `.reins/workspace/index.md` file."""

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root

    def generate_index(self) -> str:
        """Generate the workspace index markdown."""
        stats = [self._get_developer_stats(name) for name in self._get_all_developers()]
        return self._render_index(stats)

    def write_index(self) -> Path:
        """Write the rendered workspace index to disk."""
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        index_path = self.workspace_root / "index.md"
        index_path.write_text(self.generate_index(), encoding="utf-8")
        return index_path

    def _get_all_developers(self) -> list[str]:
        """Return all developer workspace directory names."""
        if not self.workspace_root.exists():
            return []

        return sorted(
            path.name
            for path in self.workspace_root.iterdir()
            if path.is_dir() and not path.name.startswith(".")
        )

    def _get_developer_stats(self, developer: str) -> DeveloperStats:
        """Collect workspace statistics for a developer."""
        journal = DeveloperJournal(self.workspace_root, developer)
        entries = journal.get_all_entries()
        journal_files = journal.get_journal_file_stats()

        return DeveloperStats(
            name=developer,
            last_active=entries[-1].timestamp if entries else None,
            sessions=len(entries),
            commits=sum(len(entry.commits) for entry in entries),
            active_file=journal_files[-1].path.name if journal_files else "-",
            journal_files=len(journal_files),
        )

    def _render_index(self, stats: list[DeveloperStats]) -> str:
        """Render workspace index markdown content."""
        lines = [
            "# Workspace Index",
            "",
            "> Records of all AI Agent work across all developers",
            "",
            "---",
            "",
            "## Overview",
            "",
            "This directory tracks work records for all developers using AI agents on this project.",
            "",
            "### File Structure",
            "",
            "```",
            "workspace/",
            "|-- index.md              # This file - main index",
            "|-- GETTING_STARTED.md    # Developer onboarding guide",
            "+-- {developer}/          # Per-developer directory",
            "    |-- index.md          # Personal index with session history",
            "    +-- journal-N.md      # Journal files (sequential: 1, 2, 3...)",
            "```",
            "",
            "---",
            "",
            "## Active Developers",
            "",
            "| Developer | Last Active | Sessions | Commits | Active File |",
            "|-----------|-------------|----------|---------|-------------|",
        ]

        for stat in sorted(
            stats,
            key=lambda item: (item.last_active or datetime.min, item.name),
            reverse=True,
        ):
            last_active = stat.last_active.strftime("%Y-%m-%d") if stat.last_active else "-"
            lines.append(
                f"| {stat.name} | {last_active} | {stat.sessions} | {stat.commits} | {stat.active_file} |"
            )

        if not stats:
            lines.append("| _None yet_ | - | 0 | 0 | - |")

        lines.extend(
            [
                "",
                "---",
                "",
                "## Getting Started",
                "",
                "For the full onboarding flow, see [GETTING_STARTED.md](GETTING_STARTED.md).",
                "",
                "### Quick Start",
                "",
                "1. Initialize your workspace with `reins workspace init <your-name>`",
                "2. Verify your stats with `reins workspace stats <your-name> --detailed`",
                "3. Start work by creating and starting a task",
                "",
                "### For New Developers",
                "",
                "Initialize your workspace:",
                "",
                "```bash",
                "reins workspace init <your-name>",
                "```",
                "",
                "This will:",
                "1. Create your workspace directory",
                "2. Create your initial journal file",
                "3. Set up your developer identity",
                "",
                "### For Returning Developers",
                "",
                "View your workspace:",
                "",
                "```bash",
                "reins workspace stats <your-name>",
                "```",
                "",
                "---",
                "",
                "## Guidelines",
                "",
                "### Journal File Rules",
                "",
                "- **Max 2000 lines** per journal file",
                "- Automatic rotation when limit reached",
                "- All journals preserved in workspace",
                "",
                "### Session Recording",
                "",
                "Record your work:",
                "",
                "```bash",
                "python3 ./.trellis/scripts/add_session.py \\",
                "  --title \"Session Title\" \\",
                "  --commit \"hash1,hash2\" \\",
                "  --summary \"Brief summary\"",
                "```",
                "",
                "---",
                "",
                "**Language**: All documentation must be written in **English**.",
            ]
        )

        return "\n".join(lines)


def write_workspace_index(workspace_root: Path) -> Path:
    """Rebuild and write the global workspace index."""
    return WorkspaceIndexGenerator(workspace_root).write_index()
