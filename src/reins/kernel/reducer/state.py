from __future__ import annotations

from dataclasses import dataclass, field

from reins.kernel.types import FailureClass, GrantRef, HandleRef, RunStatus


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
    last_checkpoint_id: str | None = None


@dataclass
class StateSnapshot:
    snapshot_id: str
    run_id: str
    event_seq: int
    reducer_version: str
    run_phase: str
    task_graph_ref: str | None = None
    open_nodes: list[str] = field(default_factory=list)
    closed_nodes: list[str] = field(default_factory=list)
    active_grants: list[GrantRef] = field(default_factory=list)
    pending_approvals: list[str] = field(default_factory=list)
    working_set_manifest_ref: str | None = None
