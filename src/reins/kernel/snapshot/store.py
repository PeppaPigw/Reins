from __future__ import annotations

import logging
from pathlib import Path

import ulid

from reins.kernel.event.journal import EventJournal
from reins.kernel.reducer.reducer import REDUCER_VERSION, reduce
from reins.kernel.reducer.state import CompletedRepair, PendingRepair, RunState, StateSnapshot
from reins.kernel.snapshot.integrity import (
    INTEGRITY_HASH_FIELD,
    compute_snapshot_hash,
    validate_snapshot_integrity,
)
from reins.kernel.types import FailureClass, GrantRef
from reins.serde import read_json, to_primitive, write_json_atomic

logger = logging.getLogger(__name__)


def _snapshot_from_dict(data: dict) -> StateSnapshot:
    grants = [GrantRef(**grant) for grant in data.get("active_grants", [])]
    pending_repair = None
    if data.get("pending_repair") is not None:
        payload = data["pending_repair"]
        pending_repair = PendingRepair(
            eval_id=payload["eval_id"],
            failure_class=FailureClass(payload["failure_class"]),
            repair_route=payload["repair_route"],
            retry_allowed=bool(payload["retry_allowed"]),
            details=payload["details"],
            repair_hints=list(payload.get("repair_hints", [])),
            command_id=payload.get("command_id"),
        )
    last_completed_repair = None
    if data.get("last_completed_repair") is not None:
        payload = data["last_completed_repair"]
        last_completed_repair = CompletedRepair(
            eval_id=payload["eval_id"],
            command_id=payload["command_id"],
            failure_class=(
                FailureClass(payload["failure_class"])
                if payload.get("failure_class") is not None
                else None
            ),
        )
    return StateSnapshot(
        snapshot_id=data["snapshot_id"],
        run_id=data["run_id"],
        event_seq=data["event_seq"],
        reducer_version=data["reducer_version"],
        run_phase=data["run_phase"],
        current_node_id=data.get("current_node_id"),
        task_graph_ref=data.get("task_graph_ref"),
        open_nodes=data.get("open_nodes", []),
        closed_nodes=data.get("closed_nodes", []),
        active_grants=grants,
        pending_approvals=data.get("pending_approvals", []),
        open_questions=data.get("open_questions", []),
        last_failure_class=(
            FailureClass(data["last_failure_class"])
            if data.get("last_failure_class") is not None
            else None
        ),
        pending_repair=pending_repair,
        repairing_command_id=data.get("repairing_command_id"),
        last_completed_repair=last_completed_repair,
        working_set_manifest_ref=data.get("working_set_manifest_ref"),
        seed_context_manifest=data.get("seed_context_manifest"),
        current_context_manifest=data.get("current_context_manifest"),
        active_task_id=data.get("active_task_id"),
        reins_version=data.get("reins_version", "unknown"),
    )


class SnapshotCorruptionError(Exception):
    """Raised when a snapshot is corrupted and cannot be rebuilt."""

    def __init__(self, run_id: str, snapshot_id: str) -> None:
        self.run_id = run_id
        self.snapshot_id = snapshot_id
        super().__init__(
            f"Snapshot {snapshot_id} for run {run_id} is corrupted and cannot be rebuilt"
        )


class SnapshotStore:
    def __init__(self, base_dir: Path, journal: EventJournal | None = None) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._journal = journal

    async def save(self, snapshot: StateSnapshot) -> None:
        path = self.base_dir / snapshot.run_id / f"{snapshot.snapshot_id}.json"
        data = to_primitive(snapshot)
        hash_value = compute_snapshot_hash(snapshot)
        data[INTEGRITY_HASH_FIELD] = hash_value
        await write_json_atomic(path, data)

    async def load(self, run_id: str, snapshot_id: str) -> StateSnapshot:
        path = self.base_dir / run_id / f"{snapshot_id}.json"
        data = await read_json(path)
        integrity_hash = data.get(INTEGRITY_HASH_FIELD)
        if integrity_hash is not None and not validate_snapshot_integrity(data, integrity_hash):
            logger.warning(
                "Snapshot %s for run %s failed integrity check, attempting rebuild",
                snapshot_id,
                run_id,
            )
            rebuilt = await self._rebuild_from_journal(run_id)
            if rebuilt is not None:
                return rebuilt
            raise SnapshotCorruptionError(run_id, snapshot_id)
        if data.get("reducer_version") != REDUCER_VERSION:
            logger.info(
                "Snapshot %s for run %s has stale reducer version (%s != %s), rebuilding",
                snapshot_id,
                run_id,
                data.get("reducer_version"),
                REDUCER_VERSION,
            )
            rebuilt = await self._rebuild_from_journal(run_id)
            if rebuilt is not None:
                return rebuilt
        return _snapshot_from_dict(data)

    async def latest(self, run_id: str) -> StateSnapshot | None:
        run_dir = self.base_dir / run_id
        if not run_dir.exists():
            return None
        candidates = sorted(
            run_dir.glob("*.json"), key=lambda path: path.stat().st_mtime
        )
        if not candidates:
            return None
        data = await read_json(candidates[-1])
        integrity_hash = data.get(INTEGRITY_HASH_FIELD)
        snapshot_id = data.get("snapshot_id", candidates[-1].stem)
        if integrity_hash is not None and not validate_snapshot_integrity(data, integrity_hash):
            logger.warning(
                "Latest snapshot for run %s failed integrity check, attempting rebuild",
                run_id,
            )
            rebuilt = await self._rebuild_from_journal(run_id)
            if rebuilt is not None:
                return rebuilt
            raise SnapshotCorruptionError(run_id, snapshot_id)
        if data.get("reducer_version") != REDUCER_VERSION:
            logger.info(
                "Latest snapshot for run %s has stale reducer version, rebuilding",
                run_id,
            )
            rebuilt = await self._rebuild_from_journal(run_id)
            if rebuilt is not None:
                return rebuilt
        return _snapshot_from_dict(data)

    async def _rebuild_from_journal(self, run_id: str) -> StateSnapshot | None:
        """Rebuild a snapshot by replaying all events from the journal."""
        if self._journal is None:
            return None
        state = RunState(run_id=run_id)
        last_seq = 0
        async for event in self._journal.read_from(run_id):
            state = reduce(state, event)
            last_seq = event.seq
        if last_seq == 0:
            return None
        new_snapshot = StateSnapshot(
            snapshot_id=str(ulid.new()),
            run_id=run_id,
            event_seq=last_seq,
            reducer_version=REDUCER_VERSION,
            run_phase=state.status.value,
            current_node_id=state.current_node_id,
            active_grants=list(state.active_grants),
            pending_approvals=list(state.pending_approvals),
            open_questions=list(state.open_questions),
            last_failure_class=state.last_failure_class,
            pending_repair=state.pending_repair,
            repairing_command_id=state.repairing_command_id,
            last_completed_repair=state.last_completed_repair,
            working_set_manifest_ref=state.working_set_manifest_ref,
            seed_context_manifest=state.seed_context_manifest,
            current_context_manifest=state.current_context_manifest,
            active_task_id=state.active_task_id,
        )
        await self.save(new_snapshot)
        return new_snapshot
