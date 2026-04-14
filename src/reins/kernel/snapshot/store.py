from __future__ import annotations

from pathlib import Path

from reins.kernel.reducer.state import CompletedRepair, PendingRepair, StateSnapshot
from reins.kernel.types import FailureClass, GrantRef
from reins.serde import read_json, to_primitive, write_json_atomic


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
    )


class SnapshotStore:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def save(self, snapshot: StateSnapshot) -> None:
        path = self.base_dir / snapshot.run_id / f"{snapshot.snapshot_id}.json"
        await write_json_atomic(path, to_primitive(snapshot))

    async def load(self, run_id: str, snapshot_id: str) -> StateSnapshot:
        path = self.base_dir / run_id / f"{snapshot_id}.json"
        return _snapshot_from_dict(await read_json(path))

    async def latest(self, run_id: str) -> StateSnapshot | None:
        run_dir = self.base_dir / run_id
        if not run_dir.exists():
            return None
        candidates = sorted(run_dir.glob("*.json"), key=lambda path: path.stat().st_mtime)
        if not candidates:
            return None
        return _snapshot_from_dict(await read_json(candidates[-1]))
