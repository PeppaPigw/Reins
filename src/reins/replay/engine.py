from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any, Callable

from reins.replay.types import (
    Breakpoint,
    Divergence,
    EventRecord,
    ReplayMode,
    ReplaySession,
    ReplayStats,
    ReplayStatus,
)


class ReplayEngine:
    """Deterministic replay engine for event-sourced agent executions.

    Records agent events with state hashes, then replays them deterministically.
    Detects divergence (non-determinism), supports breakpoints, step-through,
    and fast-forward modes. Enables "time-travel debugging" for agent failures.
    """

    def __init__(self) -> None:
        self._events: dict[str, list[EventRecord]] = {}
        self._sessions: dict[str, ReplaySession] = {}
        self._breakpoints: dict[str, list[Breakpoint]] = {}
        self._divergences: list[Divergence] = []
        self._reducer: Callable[[dict[str, Any], EventRecord], dict[str, Any]] | None = None

    def set_reducer(self, reducer: Callable[[dict[str, Any], EventRecord], dict[str, Any]]) -> None:
        self._reducer = reducer

    def record(self, run_id: str, agent_id: str, event_type: str,
               payload: dict[str, Any] | None = None,
               state: dict[str, Any] | None = None) -> EventRecord:
        if run_id not in self._events:
            self._events[run_id] = []

        sequence = len(self._events[run_id])
        state_hash = self._hash_state(state) if state else ""

        event = EventRecord(
            sequence=sequence,
            agent_id=agent_id,
            event_type=event_type,
            payload=payload or {},
            state_hash=state_hash,
        )
        self._events[run_id].append(event)
        return event

    def get_events(self, run_id: str) -> list[EventRecord]:
        return self._events.get(run_id, [])

    def start_replay(self, run_id: str,
                     mode: ReplayMode = ReplayMode.FULL) -> ReplaySession | None:
        events = self._events.get(run_id)
        if not events:
            return None

        session = ReplaySession(
            mode=mode,
            status=ReplayStatus.RUNNING,
            total_events=len(events),
        )
        self._sessions[session.session_id] = session
        return session

    def step(self, session_id: str,
             state: dict[str, Any]) -> tuple[EventRecord | None, dict[str, Any]]:
        session = self._sessions.get(session_id)
        if not session or session.status not in (ReplayStatus.RUNNING, ReplayStatus.PAUSED):
            return None, state

        run_id = self._find_run_for_session(session_id)
        if not run_id:
            return None, state

        events = self._events[run_id]
        pos = session.current_position

        if pos >= len(events):
            self._sessions[session_id] = session.model_copy(
                update={"status": ReplayStatus.COMPLETED}
            )
            return None, state

        event = events[pos]

        if self._reducer:
            new_state = self._reducer(state, event)
        else:
            new_state = {**state, **event.payload}

        actual_hash = self._hash_state(new_state)
        if event.state_hash and actual_hash != event.state_hash:
            divergence = Divergence(
                position=pos,
                expected_hash=event.state_hash,
                actual_hash=actual_hash,
                actual_state=new_state,
            )
            self._divergences.append(divergence)
            self._sessions[session_id] = session.model_copy(update={
                "status": ReplayStatus.DIVERGED,
                "current_position": pos + 1,
                "divergence_point": pos,
            })
            return event, new_state

        breakpoints = self._breakpoints.get(session_id, [])
        hit_bp = self._check_breakpoints(breakpoints, event, pos)

        new_status = ReplayStatus.PAUSED if hit_bp else ReplayStatus.RUNNING
        if pos + 1 >= len(events) and not hit_bp:
            new_status = ReplayStatus.COMPLETED

        self._sessions[session_id] = session.model_copy(update={
            "status": new_status,
            "current_position": pos + 1,
        })
        return event, new_state

    def replay_all(self, session_id: str,
                   initial_state: dict[str, Any] | None = None) -> dict[str, Any]:
        state = initial_state or {}
        while True:
            session = self._sessions.get(session_id)
            if not session or session.status not in (ReplayStatus.RUNNING,):
                break
            event, state = self.step(session_id, state)
            if event is None:
                break
        return state

    def add_breakpoint(self, session_id: str,
                       at_sequence: int | None = None,
                       at_event_type: str | None = None,
                       at_agent: str | None = None,
                       condition: str = "") -> Breakpoint:
        bp = Breakpoint(
            at_sequence=at_sequence,
            at_event_type=at_event_type,
            at_agent=at_agent,
            condition=condition,
        )
        if session_id not in self._breakpoints:
            self._breakpoints[session_id] = []
        self._breakpoints[session_id].append(bp)
        return bp

    def remove_breakpoint(self, session_id: str, breakpoint_id: str) -> bool:
        bps = self._breakpoints.get(session_id, [])
        for i, bp in enumerate(bps):
            if bp.breakpoint_id == breakpoint_id:
                bps.pop(i)
                return True
        return False

    def resume(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        if not session or session.status != ReplayStatus.PAUSED:
            return False
        self._sessions[session_id] = session.model_copy(
            update={"status": ReplayStatus.RUNNING}
        )
        return True

    def get_session(self, session_id: str) -> ReplaySession | None:
        return self._sessions.get(session_id)

    def get_divergences(self, run_id: str | None = None) -> list[Divergence]:
        return list(self._divergences)

    def get_stats(self) -> ReplayStats:
        by_mode: dict[str, int] = defaultdict(int)
        by_status: dict[str, int] = defaultdict(int)
        completed = 0
        diverged = 0
        total_replayed = 0

        for s in self._sessions.values():
            by_mode[s.mode.value] += 1
            by_status[s.status.value] += 1
            total_replayed += s.current_position
            if s.status == ReplayStatus.COMPLETED:
                completed += 1
            elif s.status == ReplayStatus.DIVERGED:
                diverged += 1

        avg = total_replayed / len(self._sessions) if self._sessions else 0.0

        return ReplayStats(
            total_sessions=len(self._sessions),
            completed_sessions=completed,
            diverged_sessions=diverged,
            total_events_replayed=total_replayed,
            avg_events_per_session=avg,
            by_mode=dict(by_mode),
            by_status=dict(by_status),
        )

    def _hash_state(self, state: dict[str, Any]) -> str:
        serialized = json.dumps(state, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode()).hexdigest()[:16]

    def _find_run_for_session(self, session_id: str) -> str | None:
        session = self._sessions.get(session_id)
        if not session:
            return None
        for run_id, events in self._events.items():
            if events and session.total_events == len(events):
                return run_id
        return None

    def _check_breakpoints(self, breakpoints: list[Breakpoint],
                           event: EventRecord, position: int) -> bool:
        for bp in breakpoints:
            if not bp.enabled:
                continue
            if bp.at_sequence is not None and bp.at_sequence == position:
                return True
            if bp.at_event_type and bp.at_event_type == event.event_type:
                return True
            if bp.at_agent and bp.at_agent == event.agent_id:
                return True
        return False
