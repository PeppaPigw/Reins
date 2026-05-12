from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class TrustLevel(str, Enum):
    supervised = "supervised"       # L0: all actions require approval
    semi_auto = "semi_auto"         # L1: low-risk auto-approved
    auto = "auto"                   # L2: medium-risk auto-approved
    full_autonomy = "full_autonomy" # L3: high-risk auto-approved (T3/T4 still gated)


class MemoryType(str, Enum):
    decision = "decision"
    pattern = "pattern"
    failure = "failure"
    preference = "preference"


class AssumptionStatus(str, Enum):
    recorded = "recorded"
    validated = "validated"
    invalidated = "invalidated"


class EscalationReason(str, Enum):
    max_retries_exceeded = "max_retries_exceeded"
    all_hypotheses_exhausted = "all_hypotheses_exhausted"
    trust_insufficient = "trust_insufficient"
    unfamiliar_domain = "unfamiliar_domain"
    cumulative_timeout = "cumulative_timeout"
    pattern_confidence_low = "pattern_confidence_low"


@dataclass(frozen=True)
class SubtaskNode:
    task_id: str
    description: str
    estimated_complexity: Literal["trivial", "low", "medium", "high", "unknown"]
    risk_tier: str
    requires_checkpoint: bool = False


@dataclass(frozen=True)
class DAGEdge:
    from_task: str
    to_task: str
    edge_type: Literal["depends_on", "informs", "blocks"] = "depends_on"


@dataclass(frozen=True)
class DAGProposal:
    objective: str
    nodes: tuple[SubtaskNode, ...]
    edges: tuple[DAGEdge, ...]
    assumptions: tuple[Assumption, ...] = ()


@dataclass(frozen=True)
class Assumption:
    assumption_id: str
    content: str
    source: str
    confidence: float
    status: AssumptionStatus = AssumptionStatus.recorded


@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    memory_type: MemoryType
    content: str
    context: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5
    source: str = ""
    source_id: str = ""


@dataclass(frozen=True)
class MemoryQuery:
    query_text: str
    memory_type: MemoryType | None = None
    context: dict[str, Any] = field(default_factory=dict)
    limit: int = 10
    min_confidence: float = 0.0


@dataclass(frozen=True)
class ScoredMemory:
    record: MemoryRecord
    relevance: float


@dataclass(frozen=True)
class TrustScore:
    domain: str
    level: TrustLevel
    score: float
    effective_successes: float
    effective_failures: float
    last_updated: str


@dataclass(frozen=True)
class StrategyRecommendation:
    strategy: str
    trust_level: TrustLevel
    requires_approval: bool
    rationale: str
    fallback_strategy: str | None = None


@dataclass(frozen=True)
class RecoveryProposal:
    failure_class: str
    assumed_failure_class: str
    fallback_classes: tuple[str, ...] = ()
    action: str = ""
    rationale: str = ""
    requires_approval: bool = True
    risk_tier: str = "medium"
    pattern_id: str | None = None
    prior_attempts: int = 0


@dataclass(frozen=True)
class HealingPattern:
    pattern_id: str
    failure_signature: str
    recovery_action: str
    success_rate: float
    applicable_domains: tuple[str, ...] = ()
    max_auto_applications: int = 3


@dataclass(frozen=True)
class EscalationDecision:
    should_escalate: bool
    reason: EscalationReason | None = None
    context: dict[str, Any] = field(default_factory=dict)
    suggested_human_action: str = ""
