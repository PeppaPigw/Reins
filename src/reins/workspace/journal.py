from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from reins.config.loader import ConfigLoader
from reins.workspace.types import JournalEntry, JournalFileStats

SESSION_HEADING_RE = re.compile(r"^## Session (\d+): (.+)$", re.MULTILINE)
DATE_RE = re.compile(r"^\*\*Date:\*\* (.+)$", re.MULTILINE)
SESSION_ID_RE = re.compile(r"^\*\*Session ID:\*\* (.+)$", re.MULTILINE)
COMMITS_RE = re.compile(r"^\*\*Commits:\*\* ?(.*)$", re.MULTILINE)
JOURNAL_FILE_RE = re.compile(r"^journal-(\d+)\.md$")


@dataclass(frozen=True)
class _ParsedJournalEntry:
    journal_file: Path
    session_number: int
    entry: JournalEntry


class DeveloperJournal:
    """Manage per-developer markdown journals with file rotation."""

    def __init__(
        self,
        workspace_dir: Path,
        developer: str,
        *,
        max_lines_per_file: int | None = None,
    ):
        self.workspace_dir = workspace_dir
        self.developer = developer
        self.journal_dir = workspace_dir / developer
        self.max_lines_per_file = max_lines_per_file or self._load_max_lines_per_file()

    def add_session(self, entry: JournalEntry) -> None:
        """Add a session entry to the active journal file."""
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        parsed_before = self._get_parsed_entries()
        session_number = len(parsed_before) + 1
        journal_file = self._get_latest_journal_file()
        session_content = self._format_entry(entry, session_number)

        if journal_file is None:
            journal_file = self._create_journal_file(1)
        elif (
            self._line_count(journal_file) + len(session_content.splitlines()) > self.max_lines_per_file
            and any(item.journal_file == journal_file for item in parsed_before)
        ):
            journal_file = self._create_journal_file(self._extract_journal_number(journal_file) + 1)

        prefix = "\n" if journal_file.read_text(encoding="utf-8") and not journal_file.read_text(encoding="utf-8").endswith("\n") else ""
        with journal_file.open("a", encoding="utf-8") as handle:
            handle.write(prefix)
            handle.write(session_content)

        current_session = self.journal_dir / ".current-session"
        current_session.write_text(f"{entry.session_id}\n", encoding="utf-8")
        self.update_index()

    def get_current_journal_file(self) -> Path:
        """Return the current active journal file, creating it if needed."""
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        journal_file = self._get_latest_journal_file()
        if journal_file is None:
            journal_file = self._create_journal_file(1)
        rotated = self.rotate_if_needed()
        return rotated or journal_file

    def rotate_if_needed(self) -> Path | None:
        """Rotate to a new file when the active journal exceeds the line budget."""
        journal_file = self._get_latest_journal_file()
        if journal_file is None:
            created = self._create_journal_file(1)
            self.update_index()
            return created

        if self._line_count(journal_file) <= self.max_lines_per_file:
            return None

        next_number = self._extract_journal_number(journal_file) + 1
        rotated = self._create_journal_file(next_number)
        self.update_index()
        return rotated

    def get_all_entries(self) -> list[JournalEntry]:
        """Load every session entry from the developer's journal files."""
        return [parsed.entry for parsed in self._get_parsed_entries()]

    def update_index(self) -> None:
        """Rewrite `index.md` with statistics and recent sessions."""
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        from reins.workspace.stats import (
            StatisticsCalculator,
            load_workspace_stats,
            write_workspace_stats,
        )

        previous_stats = load_workspace_stats(self.journal_dir, self.developer)
        calculated_stats = StatisticsCalculator().calculate_stats(self.journal_dir)
        if not calculated_stats.active_tasks and previous_stats.active_tasks:
            from dataclasses import replace

            calculated_stats = replace(
                calculated_stats,
                active_tasks=previous_stats.active_tasks,
                active_task_count=len(previous_stats.active_tasks),
            )
        write_workspace_stats(self.journal_dir, calculated_stats)
        parsed_entries = self._get_parsed_entries()
        journal_stats = self._get_journal_file_stats()
        total_commits = sum(len(entry.entry.commits) for entry in parsed_entries)
        last_active = parsed_entries[-1].entry.timestamp.strftime("%Y-%m-%d") if parsed_entries else "-"

        lines = [
            f"# Developer Workspace: {self.developer}",
            "",
            "## Statistics",
            "",
            f"- **Total Sessions:** {len(parsed_entries)}",
            f"- **Total Commits:** {total_commits}",
            f"- **Last Active:** {last_active}",
            f"- **Journal Files:** {len(journal_stats)}",
            "",
            "## Journal Files",
            "",
        ]

        if journal_stats:
            for file_stat in journal_stats:
                session_span = "No sessions yet"
                if file_stat.session_start is not None and file_stat.session_end is not None:
                    session_span = f"Sessions {file_stat.session_start}-{file_stat.session_end}"
                lines.append(
                    f"- [{file_stat.path.name}]({file_stat.path.name}) — {file_stat.line_count} lines, {session_span}"
                )
        else:
            lines.append("- None")

        lines.extend(["", "## Recent Sessions", ""])
        recent_entries = list(reversed(parsed_entries[-5:]))
        if recent_entries:
            for index, parsed_entry in enumerate(recent_entries, start=1):
                lines.append(
                    f"{index}. [{parsed_entry.entry.title}]"
                    f"({parsed_entry.journal_file.name}#session-{parsed_entry.session_number})"
                    f" — {parsed_entry.entry.timestamp.strftime('%Y-%m-%d')}"
                )
        else:
            lines.append("1. No sessions recorded yet.")

        lines.extend(["", "## Active Tasks", ""])
        active_tasks = self._load_active_tasks()
        if active_tasks:
            for task in active_tasks:
                lines.append(f"- {task}")
        else:
            lines.append("- None")

        lines.append("")
        (self.journal_dir / "index.md").write_text("\n".join(lines), encoding="utf-8")

        from reins.workspace.index_generator import write_workspace_index

        write_workspace_index(self.workspace_dir)

    def get_journal_file_stats(self) -> list[JournalFileStats]:
        """Return per-file statistics for active journal files."""
        return self._get_journal_file_stats()

    def _get_parsed_entries(self) -> list[_ParsedJournalEntry]:
        parsed_entries: list[_ParsedJournalEntry] = []
        for journal_file in self._iter_journal_files():
            content = journal_file.read_text(encoding="utf-8")
            matches = list(SESSION_HEADING_RE.finditer(content))
            for index, match in enumerate(matches):
                block_end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
                block = content[match.start() : block_end]
                parsed_entries.append(
                    _ParsedJournalEntry(
                        journal_file=journal_file,
                        session_number=int(match.group(1)),
                        entry=self._parse_block(block),
                    )
                )
        parsed_entries.sort(key=lambda item: item.session_number)
        return parsed_entries

    def _parse_block(self, block: str) -> JournalEntry:
        block = block.split("\n---", 1)[0].strip()
        heading = SESSION_HEADING_RE.search(block)
        if heading is None:
            raise ValueError("Journal block is missing a session heading.")

        timestamp_raw = self._match_or_default(DATE_RE, block, default="1970-01-01 00:00:00")
        session_id = self._match_or_default(SESSION_ID_RE, block, default="")
        commits_raw = self._match_or_default(COMMITS_RE, block, default="")
        summary = self._extract_section(block, "Summary")
        details = self._extract_section(block, "Details")
        tasks_completed = self._extract_list_section(block, "Tasks Completed")
        files_changed = self._extract_list_section(block, "Files Changed")

        return JournalEntry(
            timestamp=datetime.fromisoformat(timestamp_raw),
            session_id=session_id,
            title=heading.group(2).strip(),
            commits=[item for item in (value.strip() for value in commits_raw.split(",")) if item],
            summary=summary,
            tasks_completed=tasks_completed,
            files_changed=files_changed,
            details=details,
        )

    def _extract_section(self, block: str, title: str) -> str:
        match = re.search(rf"^### {re.escape(title)}\n\n(.*?)(?=^### |\Z)", block, re.MULTILINE | re.DOTALL)
        if match is None:
            return ""
        return match.group(1).strip()

    def _extract_list_section(self, block: str, title: str) -> list[str]:
        content = self._extract_section(block, title)
        items = [line[2:].strip() for line in content.splitlines() if line.startswith("- ")]
        return [item for item in items if item and item.lower() != "none"]

    def _match_or_default(self, pattern: re.Pattern[str], block: str, *, default: str) -> str:
        match = pattern.search(block)
        if match is None:
            return default
        return match.group(1).strip()

    def _iter_journal_files(self) -> list[Path]:
        if not self.journal_dir.exists():
            return []
        return sorted(
            (
                path
                for path in self.journal_dir.iterdir()
                if path.is_file() and JOURNAL_FILE_RE.match(path.name)
            ),
            key=self._extract_journal_number,
        )

    def _get_latest_journal_file(self) -> Path | None:
        journal_files = self._iter_journal_files()
        return journal_files[-1] if journal_files else None

    def _create_journal_file(self, number: int) -> Path:
        path = self.journal_dir / f"journal-{number}.md"
        if path.exists():
            return path

        lines = [
            f"# Journal - {self.developer} (Part {number})",
            "",
            f"> Started: {datetime.now(UTC).strftime('%Y-%m-%d')}",
            "",
            "---",
            "",
        ]
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def _format_entry(self, entry: JournalEntry, session_number: int) -> str:
        commit_line = ", ".join(entry.commits) if entry.commits else "-"
        tasks = entry.tasks_completed or ["None"]
        files_changed = entry.files_changed or ["None"]
        details = entry.details or entry.summary
        task_lines = "\n".join(f"- {item}" for item in tasks)
        file_lines = "\n".join(f"- {item}" for item in files_changed)

        return "\n".join(
            [
                f'<a id="session-{session_number}"></a>',
                f"## Session {session_number}: {entry.title}",
                "",
                f"**Date:** {entry.timestamp.isoformat(sep=' ', timespec='seconds')}",
                f"**Session ID:** {entry.session_id}",
                f"**Commits:** {commit_line}",
                "",
                "### Summary",
                "",
                entry.summary.strip() or "No summary recorded.",
                "",
                "### Tasks Completed",
                "",
                task_lines,
                "",
                "### Files Changed",
                "",
                file_lines,
                "",
                "### Details",
                "",
                details.strip() or "No additional details recorded.",
                "",
                "---",
                "",
            ]
        )

    def _get_journal_file_stats(self) -> list[JournalFileStats]:
        stats: list[JournalFileStats] = []
        parsed = self._get_parsed_entries()
        by_name: dict[str, list[int]] = {}
        for item in parsed:
            by_name.setdefault(item.journal_file.name, []).append(item.session_number)

        for journal_file in self._iter_journal_files():
            sessions = by_name.get(journal_file.name, [])
            stats.append(
                JournalFileStats(
                    path=journal_file,
                    line_count=self._line_count(journal_file),
                    session_start=min(sessions) if sessions else None,
                    session_end=max(sessions) if sessions else None,
                )
            )
        return stats

    def _load_active_tasks(self) -> list[str]:
        stats_path = self.journal_dir / ".stats.json"
        if not stats_path.exists():
            return []

        data = json.loads(stats_path.read_text(encoding="utf-8"))
        active_tasks = data.get("active_tasks", [])
        if not isinstance(active_tasks, list):
            return []
        return [str(item) for item in active_tasks]

    def _extract_journal_number(self, path: Path) -> int:
        match = JOURNAL_FILE_RE.match(path.name)
        if match is None:
            return 0
        return int(match.group(1))

    def _load_max_lines_per_file(self) -> int:
        config_root = self.workspace_dir.parent
        if not (config_root / "config.yaml").exists():
            return 2000
        try:
            return ConfigLoader(config_root).load().max_journal_lines
        except Exception:
            return 2000

    def _line_count(self, path: Path) -> int:
        if not path.exists():
            return 0
        return len(path.read_text(encoding="utf-8").splitlines())
