from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import ulid

from reins.kernel.event.journal import EventJournal
from reins.kernel.reducer.state import RunState, StateSnapshot
from reins.kernel.types import HandleRef, RunStatus
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

    async def load_any(self, checkpoint_id: str) -> CheckpointManifest:
        for run_dir in sorted(self.base_dir.iterdir()):
            if not run_dir.is_dir():
                continue
            path = run_dir / f"{checkpoint_id}.json"
            if path.exists():
                data = await read_json(path)
                return CheckpointManifest(**data)
        raise FileNotFoundError(checkpoint_id)


class DehydrationMachine:
    def can_dehydrate(self, state: RunState) -> bool:
        return state.status not in {
            RunStatus.completed,
            RunStatus.aborted,
            RunStatus.failed,
        }

    async def dehydrate(
        self,
        state: RunState,
        journal: EventJournal,
        frozen_handles: list[dict] | None = None,
    ) -> CheckpointManifest:
        event_seq = await journal.get_seq(state.run_id)
        wake_conditions = [f"approval:{item}" for item in state.pending_approvals]
        wake_conditions.extend(f"question:{item}" for item in state.open_questions)
        manifest = CheckpointManifest(
            checkpoint_id=str(ulid.new()),
            run_id=state.run_id,
            snapshot_id=state.snapshot_id,
            event_seq=event_seq,
            worktree_ref=state.working_set_manifest_ref,
            frozen_handles=(
                list(frozen_handles)
                if frozen_handles is not None
                else [to_primitive(handle) for handle in state.open_handles]
            ),
            wake_conditions=wake_conditions,
            revalidation_steps=[],
            resume_plan_ref=state.working_set_manifest_ref,
        )
        manifest.revalidation_steps = self.validate_drift_checks(manifest)
        return manifest

    async def hydrate(
        self,
        manifest: CheckpointManifest,
        snapshot: StateSnapshot | None = None,
    ) -> RunState:
        pending_approvals = (
            list(snapshot.pending_approvals) if snapshot is not None else []
        )
        for wake_condition in manifest.wake_conditions:
            if not wake_condition.startswith("approval:"):
                continue
            approval_id = wake_condition.removeprefix("approval:")
            if approval_id not in pending_approvals:
                pending_approvals.append(approval_id)

        # Validate grants haven't expired
        active_grants = list(snapshot.active_grants) if snapshot is not None else []
        valid_grants = self._filter_expired_grants(active_grants)

        return RunState(
            run_id=manifest.run_id,
            status=RunStatus.resumable,
            current_node_id=snapshot.current_node_id if snapshot is not None else None,
            snapshot_id=(
                snapshot.snapshot_id if snapshot is not None else manifest.snapshot_id
            ),
            working_set_manifest_ref=(
                snapshot.working_set_manifest_ref
                if snapshot is not None
                and snapshot.working_set_manifest_ref is not None
                else manifest.resume_plan_ref
            ),
            open_handles=[
                HandleRef(
                    handle_id=handle["handle_id"],
                    adapter_kind=handle["adapter_kind"],
                    adapter_id=handle["adapter_id"],
                )
                for handle in manifest.frozen_handles
                if {"handle_id", "adapter_kind", "adapter_id"}.issubset(handle)
            ],
            active_grants=valid_grants,
            pending_approvals=pending_approvals,
            open_questions=(
                list(snapshot.open_questions) if snapshot is not None else []
            ),
            last_failure_class=(
                snapshot.last_failure_class if snapshot is not None else None
            ),
            pending_repair=snapshot.pending_repair if snapshot is not None else None,
            repairing_command_id=(
                snapshot.repairing_command_id if snapshot is not None else None
            ),
            last_completed_repair=(
                snapshot.last_completed_repair if snapshot is not None else None
            ),
            last_checkpoint_id=manifest.checkpoint_id,
            seed_context_manifest=(
                snapshot.seed_context_manifest if snapshot is not None else None
            ),
            current_context_manifest=(
                snapshot.current_context_manifest if snapshot is not None else None
            ),
            active_task_id=(
                snapshot.active_task_id if snapshot is not None else None
            ),
        )

    def _filter_expired_grants(self, grants: list) -> list:
        """Remove expired grants during hydration."""
        now = time.time()
        valid_grants = []
        for grant in grants:
            if grant.issued_at + grant.ttl_seconds >= now:
                valid_grants.append(grant)
        return valid_grants

    def validate_drift_checks(self, manifest: CheckpointManifest) -> list[str]:
        checks = ["replay_journal_since_checkpoint", "revalidate_policy_grants"]
        if manifest.frozen_handles:
            checks.append("restore_or_reopen_handles")
        if manifest.worktree_ref:
            checks.append("verify_worktree_ref")
        return checks
