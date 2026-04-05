from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import ulid

from reins.kernel.event.journal import EventJournal
from reins.kernel.reducer.state import RunState
from reins.kernel.types import RunStatus
from reins.serde import read_json, to_primitive, write_json_atomic


@dataclass
class CheckpointManifest:
    checkpoint_id: str
    run_id: str
    snapshot_id: str | None
    event_seq: int
    worktree_ref: str | None
    frozen_handles: list[dict] = field(default_factory=list)
    wake_conditions: list[str] = field(default_factory=list)
    revalidation_steps: list[str] = field(default_factory=list)
    secret_leases: list[str] = field(default_factory=list)
    resume_plan_ref: str | None = None


class CheckpointStore:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def save(self, manifest: CheckpointManifest) -> None:
        path = self.base_dir / manifest.run_id / f"{manifest.checkpoint_id}.json"
        await write_json_atomic(path, to_primitive(manifest))

    async def load(self, run_id: str, checkpoint_id: str) -> CheckpointManifest:
        data = await read_json(self.base_dir / run_id / f"{checkpoint_id}.json")
        return CheckpointManifest(**data)


class DehydrationMachine:
    def can_dehydrate(self, state: RunState) -> bool:
        return state.status not in {RunStatus.completed, RunStatus.aborted, RunStatus.failed}

    async def dehydrate(self, state: RunState, journal: EventJournal) -> CheckpointManifest:
        event_seq = await journal.get_seq(state.run_id)
        wake_conditions = [f"approval:{item}" for item in state.pending_approvals]
        wake_conditions.extend(f"question:{item}" for item in state.open_questions)
        manifest = CheckpointManifest(
            checkpoint_id=str(ulid.new()),
            run_id=state.run_id,
            snapshot_id=state.snapshot_id,
            event_seq=event_seq,
            worktree_ref=state.working_set_manifest_ref,
            frozen_handles=[to_primitive(handle) for handle in state.open_handles],
            wake_conditions=wake_conditions,
            revalidation_steps=[],
            resume_plan_ref=state.working_set_manifest_ref,
        )
        manifest.revalidation_steps = self.validate_drift_checks(manifest)
        return manifest

    async def hydrate(self, manifest: CheckpointManifest) -> RunState:
        return RunState(
            run_id=manifest.run_id,
            status=RunStatus.resumable,
            snapshot_id=manifest.snapshot_id,
            working_set_manifest_ref=manifest.resume_plan_ref,
            pending_approvals=[item.removeprefix("approval:") for item in manifest.wake_conditions if item.startswith("approval:")],
            last_checkpoint_id=manifest.checkpoint_id,
        )

    def validate_drift_checks(self, manifest: CheckpointManifest) -> list[str]:
        checks = ["replay_journal_since_checkpoint", "revalidate_policy_grants"]
        if manifest.frozen_handles:
            checks.append("restore_or_reopen_handles")
        if manifest.worktree_ref:
            checks.append("verify_worktree_ref")
        return checks
