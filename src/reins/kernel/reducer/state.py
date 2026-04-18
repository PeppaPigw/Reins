from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from reins.kernel.types import FailureClass, GrantRef, HandleRef, RunStatus


@dataclass(frozen=True)
class PendingRepair:
    eval_id: str
    failure_class: FailureClass
    repair_route: str
    retry_allowed: bool
    details: str
    repair_hints: list[str] = field(default_factory=list)
    command_id: str | None = None


@dataclass(frozen=True)
class CompletedRepair:
    eval_id: str
    command_id: str
    failure_class: FailureClass | None = None


@dataclass
class RunState:
    run_id: str
    status: RunStatus = RunStatus.created
    current_node_id: str | None = None
    snapshot_id: str | None = None
    working_set_manifest_ref: str | None = None
    open_handles: list[HandleRef] = field(default_factory=list)
    active_grants: list[GrantRef] = field(default_factory=list)
    pending_approvals: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    last_failure_class: FailureClass | None = None
    pending_repair: PendingRepair | None = None
    repairing_command_id: str | None = None
    last_completed_repair: CompletedRepair | None = None
    last_checkpoint_id: str | None = None

    # Reins v2.0: Context injection state
    seed_context_manifest: dict[str, Any] | None = None
    """Seed context manifest from bootstrap (ContextAssemblyManifest as dict)"""

    current_context_manifest: dict[str, Any] | None = None
    """Current context manifest (may be enriched from seed)"""

    # Reins v2.0: Task management state
    active_task_id: str | None = None
    """Currently active task ID"""


@dataclass
class StateSnapshot:
    snapshot_id: str
    run_id: str
    event_seq: int
    reducer_version: str
    run_phase: str
    current_node_id: str | None = None
    task_graph_ref: str | None = None
    open_nodes: list[str] = field(default_factory=list)
    closed_nodes: list[str] = field(default_factory=list)
    active_grants: list[GrantRef] = field(default_factory=list)
    pending_approvals: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    last_failure_class: FailureClass | None = None
    pending_repair: PendingRepair | None = None
    repairing_command_id: str | None = None
    last_completed_repair: CompletedRepair | None = None
    working_set_manifest_ref: str | None = None

    # Reins v2.0: Context injection state
    seed_context_manifest: dict[str, Any] | None = None
    current_context_manifest: dict[str, Any] | None = None

    # Reins v2.0: Task management state
    active_task_id: str | None = None
