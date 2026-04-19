from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, time
from pathlib import Path

from reins.kernel.event.envelope import event_from_dict
from reins.kernel.event.task_events import TASK_COMPLETED
from reins.workspace.journal import DeveloperJournal
from reins.workspace.types import ActivityReport


class ActivityReporter:
    """Generate developer activity reports from journals and event history."""

    def __init__(self, reins_root: Path):
        self.reins_root = reins_root

    def generate_activity_report(
        self,
        developer: str,
        start_date: datetime,
        end_date: datetime,
    ) -> ActivityReport:
        """Build an activity report for the requested date window."""
        window_start = self._normalize_start(start_date)
        window_end = self._normalize_end(end_date)
        journal = DeveloperJournal(self.reins_root / "workspace", developer)
        entries = [
            entry
            for entry in journal.get_all_entries()
            if window_start <= self._normalize_timestamp(entry.timestamp) <= window_end
        ]

        unique_commits = sorted({commit for entry in entries for commit in entry.commits})
        files_changed = {path for entry in entries for path in entry.files_changed}
        lines_added, lines_removed = self._sum_numstat(unique_commits)

        return ActivityReport(
            developer=developer,
            period=f"{window_start.date().isoformat()}..{window_end.date().isoformat()}",
            sessions_count=len(entries),
            commits_count=len(unique_commits),
            tasks_completed=self._count_completed_tasks(developer, window_start, window_end),
            files_changed=len(files_changed),
            lines_added=lines_added,
            lines_removed=lines_removed,
        )

    def _count_completed_tasks(
        self,
        developer: str,
        start_date: datetime,
        end_date: datetime,
    ) -> int:
        journal_path = self.reins_root / "journal.jsonl"
        if not journal_path.exists():
            return 0

        count = 0
        for line in journal_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = event_from_dict(json.loads(line))
            timestamp = self._normalize_timestamp(event.ts)
            if (
                event.type == TASK_COMPLETED
                and event.developer == developer
                and start_date <= timestamp <= end_date
            ):
                count += 1
        return count

    def _sum_numstat(self, commits: list[str]) -> tuple[int, int]:
        if not commits:
            return 0, 0

        repo_root = self.reins_root.parent
        added = 0
        removed = 0
        for commit in commits:
            try:
                result = subprocess.run(
                    ["git", "show", "--numstat", "--format=", commit],
                    cwd=repo_root,
                    capture_output=True,
                    text=True,
                    check=True,
                )
            except (OSError, subprocess.CalledProcessError):
                continue

            for line in result.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                if parts[0].isdigit():
                    added += int(parts[0])
                if parts[1].isdigit():
                    removed += int(parts[1])
        return added, removed

    def _normalize_start(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return datetime.combine(value.date(), time.min, tzinfo=UTC)
        return value.astimezone(UTC)

    def _normalize_end(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return datetime.combine(value.date(), time.max, tzinfo=UTC)
        return value.astimezone(UTC)

    def _normalize_timestamp(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
