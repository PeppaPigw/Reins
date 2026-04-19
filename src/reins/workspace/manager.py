from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from reins.kernel.event.builder import EventBuilder
from reins.kernel.event.journal import EventJournal
from reins.kernel.event.workspace_events import WORKSPACE_CLEANED, WORKSPACE_INITIALIZED
from reins.workspace.journal import DeveloperJournal
from reins.workspace.stats import (
    build_workspace_stats,
    load_workspace_stats,
    write_workspace_stats,
)
from reins.workspace.types import WorkspaceStats


class WorkspaceManager:
    """Manage isolated developer workspaces under `.reins/workspace/`."""

    def __init__(
        self,
        reins_root: Path,
        *,
        journal: EventJournal | None = None,
        run_id: str | None = None,
    ):
        self.reins_root = reins_root
        self.workspace_root = reins_root / "workspace"
        self._journal = journal
        self._run_id = run_id or "workspace-manager"

    def initialize_workspace(self, developer: str) -> Path:
        """Initialize a workspace directory for a developer."""
        workspace_dir = self.workspace_root / developer
        workspace_dir.mkdir(parents=True, exist_ok=True)

        developer_journal = DeveloperJournal(self.workspace_root, developer)
        developer_journal.get_current_journal_file()
        current_session_path = workspace_dir / ".current-session"
        current_session_path.touch(exist_ok=True)

        stats = self._refresh_workspace_stats(developer)
        if self._journal is not None:
            payload = {
                "developer": developer,
                "workspace_dir": str(workspace_dir),
                "stats_path": str(workspace_dir / ".stats.json"),
                "journal_files": stats.journal_files,
            }
            self._commit_event(WORKSPACE_INITIALIZED, payload)
        return workspace_dir

    def get_workspace(self, developer: str) -> Path | None:
        """Return the workspace directory for a developer when it exists."""
        workspace_dir = self.workspace_root / developer
        return workspace_dir if workspace_dir.exists() else None

    def list_workspaces(self) -> list[str]:
        """List all initialized developer workspaces."""
        if not self.workspace_root.exists():
            return []
        return sorted(path.name for path in self.workspace_root.iterdir() if path.is_dir())

    def cleanup_workspace(
        self,
        developer: str,
        keep_recent_days: int = 30,
    ) -> None:
        """Archive journal files whose sessions are all older than the retention window."""
        workspace_dir = self.get_workspace(developer)
        if workspace_dir is None:
            raise ValueError(f"Workspace not found for developer: {developer}")

        developer_journal = DeveloperJournal(self.workspace_root, developer)
        parsed_entries = developer_journal._get_parsed_entries()  # noqa: SLF001
        grouped_entries: dict[Path, list[datetime]] = defaultdict(list)
        for item in parsed_entries:
            grouped_entries[item.journal_file].append(item.entry.timestamp)

        journal_files = sorted(workspace_dir.glob("journal-*.md"))
        if len(journal_files) <= 1:
            self._refresh_workspace_stats(developer)
            return

        archive_dir = workspace_dir / "archive"
        archive_dir.mkdir(exist_ok=True)
        cutoff = datetime.now(UTC) - timedelta(days=keep_recent_days)
        latest_journal = journal_files[-1]
        archived_files: list[str] = []

        for journal_file in journal_files[:-1]:
            timestamps = grouped_entries.get(journal_file, [])
            if timestamps and max(timestamps).astimezone(UTC) < cutoff:
                target = archive_dir / journal_file.name
                if target.exists():
                    target.unlink()
                journal_file.replace(target)
                archived_files.append(target.name)

        self._refresh_workspace_stats(developer)
        if self._journal is not None:
            self._commit_event(
                WORKSPACE_CLEANED,
                {
                    "developer": developer,
                    "workspace_dir": str(workspace_dir),
                    "archived_files": archived_files,
                    "keep_recent_days": keep_recent_days,
                    "active_journal": latest_journal.name,
                },
            )

    def get_workspace_stats(self, developer: str) -> WorkspaceStats:
        """Return persisted statistics for a developer workspace."""
        workspace_dir = self.get_workspace(developer)
        if workspace_dir is None:
            raise ValueError(f"Workspace not found for developer: {developer}")
        return self._refresh_workspace_stats(developer)

    def _refresh_workspace_stats(self, developer: str) -> WorkspaceStats:
        workspace_dir = self.workspace_root / developer
        developer_journal = DeveloperJournal(self.workspace_root, developer)
        previous = load_workspace_stats(workspace_dir, developer)
        current_session_path = workspace_dir / ".current-session"
        current_session_id = None
        if current_session_path.exists():
            current_session_id = current_session_path.read_text(encoding="utf-8").strip() or None

        archive_dir = workspace_dir / "archive"
        archived_count = len(list(archive_dir.glob("journal-*.md"))) if archive_dir.exists() else 0
        stats = build_workspace_stats(
            developer,
            developer_journal,
            active_tasks=previous.active_tasks,
            archived_journal_files=archived_count,
            current_session_id=current_session_id,
        )
        write_workspace_stats(workspace_dir, stats)
        developer_journal.update_index()
        return stats

    def _commit_event(self, event_type: str, payload: dict[str, object]) -> None:
        builder = EventBuilder(self._journal)  # type: ignore[arg-type]
        import asyncio

        asyncio.run(builder.commit(run_id=self._run_id, event_type=event_type, payload=payload))
