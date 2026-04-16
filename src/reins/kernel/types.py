from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum


class RunStatus(str, Enum):
    created = "created"
    routing = "routing"
    planning = "planning"
    executing = "executing"
    evaluating = "evaluating"
    waiting_approval = "waiting_approval"
    waiting_external = "waiting_external"
    dehydrated = "dehydrated"
    resumable = "resumable"
    completed = "completed"
    aborted = "aborted"
    failed = "failed"


class Actor(str, Enum):
    runtime = "runtime"
    policy = "policy"
    evaluator = "evaluator"
    scheduler = "scheduler"
    human = "human"


class RiskTier(IntEnum):
    T0 = 0
    T1 = 1
    T2 = 2
    T3 = 3
    T4 = 4


class FailureClass(str, Enum):
    logic_failure = "logic_failure"
    context_failure = "context_failure"
    environment_failure = "environment_failure"
    policy_block = "policy_block"
    flaky_eval = "flaky_eval"
    merge_conflict = "merge_conflict"
    external_effect_failure = "external_effect_failure"
    remote_agent_failure = "remote_agent_failure"
    skill_activation_failure = "skill_activation_failure"


class PathKind(str, Enum):
    fast = "fast"
    deliberative = "deliberative"


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    kind: str
    uri: str


@dataclass(frozen=True)
class HandleRef:
    handle_id: str
    adapter_kind: str
    adapter_id: str


@dataclass(frozen=True)
class GrantRef:
    grant_id: str
    capability: str
    scope: str
    issued_to: str
    ttl_seconds: int
    approval_hash: str | None
    issued_at: float  # Unix timestamp when grant was issued
    inherited: bool = False
