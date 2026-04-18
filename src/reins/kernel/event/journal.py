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
            stored = replace(event, seq=next_seq + 1)
            line = json.dumps(event_to_dict(stored), sort_keys=True) + "\n"

            run_path = self._get_run_path(event.run_id)
            run_path.parent.mkdir(parents=True, exist_ok=True)

            async with aiofiles.open(run_path, "a", encoding="utf-8") as handle:
                await handle.write(line)
                await handle.flush()
                await asyncio.to_thread(os.fsync, handle.fileno())
            self._seq_cache[event.run_id] = stored.seq
            return stored

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
