from __future__ import annotations

from pathlib import Path

from reins.kernel.reducer.state import StateSnapshot
from reins.kernel.types import GrantRef
from reins.serde import read_json, to_primitive, write_json_atomic


def _snapshot_from_dict(data: dict) -> StateSnapshot:
    grants = [GrantRef(**grant) for grant in data.get("active_grants", [])]
    return StateSnapshot(
        snapshot_id=data["snapshot_id"],
        run_id=data["run_id"],
        event_seq=data["event_seq"],
        reducer_version=data["reducer_version"],
        run_phase=data["run_phase"],
        task_graph_ref=data.get("task_graph_ref"),
        open_nodes=data.get("open_nodes", []),
        closed_nodes=data.get("closed_nodes", []),
        active_grants=grants,
        pending_approvals=data.get("pending_approvals", []),
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
