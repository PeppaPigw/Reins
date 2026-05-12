from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass

import aiofiles  # type: ignore[import-untyped]

from reins.kernel.event.envelope import EventEnvelope, event_from_dict, event_to_dict
from reins.kernel.event.journal import EventJournal
from reins.kernel.snapshot.store import SnapshotStore


@dataclass
class RetentionPolicy:
    """Configurable retention policy for journal compaction."""

    max_events: int = 10_000
    keep_last_n: int = 1_000
    keep_after_snapshot: bool = True
    preserve_causation: bool = True


async def should_compact(
    journal: EventJournal, run_id: str, policy: RetentionPolicy
) -> bool:
    """Determine if a journal for a run_id should be compacted."""
    count = 0
    async for _ in journal.read_from(run_id):
        count += 1
        if count > policy.max_events:
            return True
    return count > policy.max_events


async def compact_journal(
    journal: EventJournal,
    run_id: str,
    policy: RetentionPolicy,
    snapshot_store: SnapshotStore | None = None,
) -> int:
    """Compact a journal for a run_id based on the retention policy.

    Returns the number of events removed.
    """
    # Read all events
    all_events: list[EventEnvelope] = []
    async for event in journal.read_from(run_id):
        all_events.append(event)

    if len(all_events) <= policy.keep_last_n:
        return 0

    # Determine the snapshot boundary seq
    snapshot_seq = 0
    if policy.keep_after_snapshot and snapshot_store is not None:
        latest_snap = await snapshot_store.latest(run_id)
        if latest_snap is not None:
            snapshot_seq = latest_snap.event_seq

    # Determine which events to keep
    keep_set: set[int] = set()

    # Always keep the last N events
    last_n_start = len(all_events) - policy.keep_last_n
    for i in range(max(0, last_n_start), len(all_events)):
        keep_set.add(i)

    # Keep events after snapshot boundary
    if policy.keep_after_snapshot and snapshot_seq > 0:
        for i, event in enumerate(all_events):
            if event.seq >= snapshot_seq:
                keep_set.add(i)

    # Preserve causation chains
    if policy.preserve_causation:
        # Build a set of causation_ids referenced by kept events
        needed_causation_ids: set[str] = set()
        for i in keep_set:
            event = all_events[i]
            if event.causation_id:
                needed_causation_ids.add(event.causation_id)

        # Add events whose event_id is referenced as a causation_id
        for i, event in enumerate(all_events):
            if event.event_id in needed_causation_ids:
                keep_set.add(i)

    # Build the retained events list (preserving order)
    retained_events = [all_events[i] for i in sorted(keep_set)]
    removed_count = len(all_events) - len(retained_events)

    if removed_count == 0:
        return 0

    # Rewrite the journal atomically
    run_path = journal._get_run_path(run_id)
    temp_path = run_path.with_suffix(".jsonl.tmp")

    async with aiofiles.open(temp_path, "w", encoding="utf-8") as handle:
        for event in retained_events:
            line = json.dumps(event_to_dict(event), sort_keys=True) + "\n"
            await handle.write(line)
        await handle.flush()
        await asyncio.to_thread(os.fsync, handle.fileno())

    temp_path.replace(run_path)

    # Update the seq cache
    if retained_events:
        journal._seq_cache[run_id] = retained_events[-1].seq

    return removed_count
