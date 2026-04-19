from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import AsyncIterator

import aiofiles  # type: ignore[import-untyped]

from reins.kernel.event.envelope import EventEnvelope, event_from_dict, event_to_dict
from reins.serde import parse_dt

TimestampLike = datetime | str


def normalize_timestamp(value: TimestampLike) -> datetime:
    """Normalize supported timestamp inputs to an aware UTC datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = parse_dt(normalized)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


class EventJournal:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._is_directory = self.path.is_dir() or (
            not self.path.exists() and not self.path.suffix
        )

        if self._is_directory:
            # Directory mode: create separate file per run_id
            self.path.mkdir(parents=True, exist_ok=True)
        else:
            # File mode: single file for all runs
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.touch(exist_ok=True)

        self._lock = asyncio.Lock()
        self._seq_cache: dict[str, int] = {}

    def _get_run_path(self, run_id: str) -> Path:
        """Get the file path for a specific run_id."""
        if self._is_directory:
            return self.path / f"{run_id}.jsonl"
        return self.path

    async def append(self, event: EventEnvelope) -> EventEnvelope:
        async with self._lock:
            next_seq = self._seq_cache.get(event.run_id)
            if next_seq is None:
                next_seq = await self.get_seq(event.run_id)
            enriched = self._enrich_event(event)
            stored = replace(enriched, seq=next_seq + 1)
            line = json.dumps(event_to_dict(stored), sort_keys=True) + "\n"

            run_path = self._get_run_path(event.run_id)
            run_path.parent.mkdir(parents=True, exist_ok=True)

            async with aiofiles.open(run_path, "a", encoding="utf-8") as handle:
                await handle.write(line)
                await handle.flush()
                await asyncio.to_thread(os.fsync, handle.fileno())
            self._seq_cache[event.run_id] = stored.seq
            return stored

    def _enrich_event(self, event: EventEnvelope) -> EventEnvelope:
        developer = event.developer or self._load_current_developer()
        session_id = event.session_id or self._load_current_session_id(developer)
        task_id = event.task_id or self._extract_task_id(event.payload)
        if developer == event.developer and session_id == event.session_id and task_id == event.task_id:
            return event
        return replace(event, developer=developer, session_id=session_id, task_id=task_id)

    def _extract_task_id(self, payload: dict[str, object]) -> str | None:
        task_id = payload.get("task_id")
        if isinstance(task_id, str):
            return task_id
        return None

    def _load_current_developer(self) -> str | None:
        reins_root = self._find_reins_root()
        if reins_root is None:
            return None

        developer_path = reins_root / ".developer"
        if not developer_path.exists():
            return None

        content = developer_path.read_text(encoding="utf-8").strip()
        if not content:
            return None

        for line in content.splitlines():
            if line.startswith("name="):
                return line.split("=", 1)[1].strip() or None
        return content.splitlines()[0].strip() or None

    def _load_current_session_id(self, developer: str | None) -> str | None:
        if not developer:
            return None

        reins_root = self._find_reins_root()
        if reins_root is None:
            return None

        session_path = reins_root / "workspace" / developer / ".current-session"
        if not session_path.exists():
            return None
        return session_path.read_text(encoding="utf-8").strip() or None

    def _find_reins_root(self) -> Path | None:
        start = self.path if self._is_directory else self.path.parent
        for candidate in (start, *start.parents):
            if candidate.name == ".reins":
                return candidate
        return None

    async def read_from(
        self, run_id: str, from_seq: int = 0
    ) -> AsyncIterator[EventEnvelope]:
        run_path = self._get_run_path(run_id)
        if not run_path.exists():
            return

        async with aiofiles.open(run_path, "r", encoding="utf-8") as handle:
            async for line in handle:
                if not line.strip():
                    continue
                event = event_from_dict(json.loads(line))
                if event.run_id == run_id and event.seq >= from_seq:
                    yield event

    async def read_until(
        self,
        run_id: str,
        *,
        timestamp: TimestampLike,
        from_seq: int = 0,
    ) -> AsyncIterator[EventEnvelope]:
        """Yield events for a run up to and including the supplied timestamp."""
        cutoff = normalize_timestamp(timestamp)
        async for event in self.read_from(run_id, from_seq=from_seq):
            if event.ts <= cutoff:
                yield event

    async def get_seq(self, run_id: str) -> int:
        if run_id in self._seq_cache:
            return self._seq_cache[run_id]

        run_path = self._get_run_path(run_id)
        if not run_path.exists():
            return 0

        seq = 0
        async with aiofiles.open(run_path, "r", encoding="utf-8") as handle:
            async for line in handle:
                if not line.strip():
                    continue
                data = json.loads(line)
                if data.get("run_id") == run_id:
                    seq = max(seq, int(data.get("seq", 0)))
        self._seq_cache[run_id] = seq
        return seq
