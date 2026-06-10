from __future__ import annotations

import copy
from typing import Any, Callable

from reins.testing.timetravel_types import (
    BisectResult,
    Checkpoint,
    DiffEntry,
    DiffKind,
    FieldChange,
    FieldHistory,
    StateFrame,
    StateDiff,
    TimelineQuery,
)


class TimeTravelDebugger:
    """Reconstructs any past state from event history for debugging.

    Leverages event sourcing to provide:
    - State reconstruction at any point in time
    - Diffing between arbitrary states
    - Binary search (bisect) to find when a predicate first became true
    - Field-level change history tracking
    - Named checkpoints for quick navigation
    """

    def __init__(self, reducer: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]) -> None:
        self._reducer = reducer
        self._events: list[dict[str, Any]] = []
        self._frames: list[StateFrame] = []
        self._checkpoints: dict[str, Checkpoint] = {}
        self._initial_state: dict[str, Any] = {}

    @property
    def event_count(self) -> int:
        return len(self._events)

    @property
    def frame_count(self) -> int:
        return len(self._frames)

    def load_events(self, events: list[dict[str, Any]], initial_state: dict[str, Any] | None = None) -> None:
        self._events = list(events)
        self._initial_state = initial_state or {}
        self._rebuild_frames()

    def append_event(self, event: dict[str, Any]) -> StateFrame:
        self._events.append(event)
        prev_state = self._frames[-1].state if self._frames else self._initial_state
        new_state = self._reducer(prev_state, event)
        seq = len(self._frames) + 1
        frame = StateFrame(
            sequence=seq,
            state=new_state,
            event_type=event.get("type", "unknown"),
            metadata=event.get("metadata", {}),
        )
        self._frames.append(frame)
        return frame

    def state_at(self, sequence: int) -> dict[str, Any]:
        if sequence <= 0:
            return dict(self._initial_state)
        if sequence > len(self._frames):
            raise IndexError(f"Sequence {sequence} out of range (max {len(self._frames)})")
        return dict(self._frames[sequence - 1].state)

    def current_state(self) -> dict[str, Any]:
        if not self._frames:
            return dict(self._initial_state)
        return dict(self._frames[-1].state)

    def frame_at(self, sequence: int) -> StateFrame:
        if sequence < 1 or sequence > len(self._frames):
            raise IndexError(f"Sequence {sequence} out of range")
        return self._frames[sequence - 1]

    def diff(self, from_seq: int, to_seq: int) -> StateDiff:
        state_a = self.state_at(from_seq)
        state_b = self.state_at(to_seq)
        changes = self._compute_diff(state_a, state_b)

        added = sum(1 for c in changes if c.kind == DiffKind.ADDED)
        removed = sum(1 for c in changes if c.kind == DiffKind.REMOVED)
        modified = sum(1 for c in changes if c.kind == DiffKind.MODIFIED)
        summary = f"{added} added, {removed} removed, {modified} modified"

        return StateDiff(
            from_sequence=from_seq,
            to_sequence=to_seq,
            changes=tuple(changes),
            summary=summary,
        )

    def bisect(self, predicate: Callable[[dict[str, Any]], bool], description: str = "") -> BisectResult | None:
        if not self._frames:
            return None

        if predicate(self._initial_state):
            return BisectResult(
                found_at_sequence=0,
                event_type="initial",
                total_steps=0,
                predicate_description=description,
                state_before={},
                state_after=self._initial_state,
            )

        if not predicate(self._frames[-1].state):
            return None

        lo, hi = 0, len(self._frames) - 1
        steps = 0

        while lo < hi:
            mid = (lo + hi) // 2
            steps += 1
            if predicate(self._frames[mid].state):
                hi = mid
            else:
                lo = mid + 1

        found_frame = self._frames[lo]
        state_before = self._initial_state if lo == 0 else self._frames[lo - 1].state

        return BisectResult(
            found_at_sequence=found_frame.sequence,
            event_type=found_frame.event_type,
            total_steps=steps,
            predicate_description=description,
            state_before=state_before,
            state_after=found_frame.state,
        )

    def field_history(self, query: TimelineQuery) -> FieldHistory:
        changes: list[FieldChange] = []
        prev_value = _get_nested(self._initial_state, query.field_path)

        for frame in self._frames:
            if query.to_sequence and frame.sequence > query.to_sequence:
                break

            current_value = _get_nested(frame.state, query.field_path)
            in_range = frame.sequence >= (query.from_sequence or 0)

            if in_range and (current_value != prev_value or query.include_unchanged):
                changes.append(FieldChange(
                    sequence=frame.sequence,
                    event_type=frame.event_type,
                    old_value=prev_value,
                    new_value=current_value,
                    timestamp=frame.timestamp,
                ))
            prev_value = current_value

        return FieldHistory(field_path=query.field_path, changes=tuple(changes))

    def checkpoint(self, name: str, sequence: int | None = None) -> Checkpoint:
        seq = sequence or len(self._frames)
        state = self.state_at(seq)
        cp = Checkpoint(name=name, sequence=seq, state=state)
        self._checkpoints[name] = cp
        return cp

    def restore_checkpoint(self, name: str) -> dict[str, Any]:
        if name not in self._checkpoints:
            raise KeyError(f"Checkpoint '{name}' not found")
        return dict(self._checkpoints[name].state)

    def list_checkpoints(self) -> list[Checkpoint]:
        return sorted(self._checkpoints.values(), key=lambda c: c.sequence)

    def find_events(self, event_type: str) -> list[StateFrame]:
        return [f for f in self._frames if f.event_type == event_type]

    def slice(self, from_seq: int, to_seq: int) -> list[StateFrame]:
        return [f for f in self._frames if from_seq <= f.sequence <= to_seq]

    def _rebuild_frames(self) -> None:
        self._frames = []
        state = copy.deepcopy(self._initial_state)
        for i, event in enumerate(self._events, 1):
            state = self._reducer(copy.deepcopy(state), event)
            frame = StateFrame(
                sequence=i,
                state=copy.deepcopy(state),
                event_type=event.get("type", "unknown"),
                metadata=event.get("metadata", {}),
            )
            self._frames.append(frame)

    def _compute_diff(self, state_a: dict[str, Any], state_b: dict[str, Any]) -> list[DiffEntry]:
        entries = []
        all_keys = set(state_a.keys()) | set(state_b.keys())

        for key in sorted(all_keys):
            if key not in state_a:
                entries.append(DiffEntry(path=key, kind=DiffKind.ADDED, new_value=state_b[key]))
            elif key not in state_b:
                entries.append(DiffEntry(path=key, kind=DiffKind.REMOVED, old_value=state_a[key]))
            elif state_a[key] != state_b[key]:
                entries.append(DiffEntry(path=key, kind=DiffKind.MODIFIED, old_value=state_a[key], new_value=state_b[key]))

        return entries


def _get_nested(data: dict[str, Any], path: str) -> Any:
    parts = path.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current
