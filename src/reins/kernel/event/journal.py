from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import AsyncIterator

import aiofiles  # type: ignore[import-untyped]

from reins.kernel.event.envelope import EventEnvelope, event_from_dict, event_to_dict


class EventJournal:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._lock = asyncio.Lock()
        self._seq_cache: dict[str, int] = {}

    async def append(self, event: EventEnvelope) -> EventEnvelope:
        async with self._lock:
            next_seq = self._seq_cache.get(event.run_id)
            if next_seq is None:
                next_seq = await self.get_seq(event.run_id)
            stored = replace(event, seq=next_seq + 1)
            line = json.dumps(event_to_dict(stored), sort_keys=True) + "\n"
            async with aiofiles.open(self.path, "a", encoding="utf-8") as handle:
                await handle.write(line)
                await handle.flush()
                await asyncio.to_thread(os.fsync, handle.fileno())
            self._seq_cache[event.run_id] = stored.seq
            return stored

    async def read_from(self, run_id: str, from_seq: int = 0) -> AsyncIterator[EventEnvelope]:
        async with aiofiles.open(self.path, "r", encoding="utf-8") as handle:
            async for line in handle:
                if not line.strip():
                    continue
                event = event_from_dict(json.loads(line))
                if event.run_id == run_id and event.seq >= from_seq:
                    yield event

    async def get_seq(self, run_id: str) -> int:
        if run_id in self._seq_cache:
            return self._seq_cache[run_id]
        seq = 0
        async with aiofiles.open(self.path, "r", encoding="utf-8") as handle:
            async for line in handle:
                if not line.strip():
                    continue
                data = json.loads(line)
                if data.get("run_id") == run_id:
                    seq = max(seq, int(data.get("seq", 0)))
        self._seq_cache[run_id] = seq
        return seq
