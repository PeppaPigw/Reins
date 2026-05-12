from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class IntelligenceEvent:
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    trace_id: str = ""
    causation_id: str = ""


# --- Decomposer events ---

DAG_PROPOSED = "intel.dag.proposed"
DAG_VALIDATED = "intel.dag.validated"
DAG_RESTRUCTURED = "intel.dag.restructured"
ASSUMPTION_RECORDED = "intel.assumption.recorded"
ASSUMPTION_VALIDATED = "intel.assumption.validated"
ASSUMPTION_INVALIDATED = "intel.assumption.invalidated"
CHECKPOINT_TRIGGERED = "intel.checkpoint.triggered"

# --- Memory events ---

MEMORY_CREATED = "intel.memory.created"
MEMORY_ACCESSED = "intel.memory.accessed"
MEMORY_REINFORCED = "intel.memory.reinforced"
MEMORY_SUPERSEDED = "intel.memory.superseded"
MEMORY_CONFIDENCE_ADJUSTED = "intel.memory.confidence_adjusted"

# --- Strategy events ---

STRATEGY_RECOMMENDED = "intel.strategy.recommended"
TRUST_PROMOTED = "intel.trust.promoted"
TRUST_DEMOTED = "intel.trust.demoted"
TRUST_DECAYED = "intel.trust.decayed"

# --- Recovery events ---

RECOVERY_PLANNED = "intel.recovery.planned"
RECOVERY_SUCCEEDED = "intel.recovery.succeeded"
RECOVERY_FAILED = "intel.recovery.failed"
PATTERN_CREATED = "intel.pattern.created"
PATTERN_RETIRED = "intel.pattern.retired"
ESCALATION_TRIGGERED = "intel.escalation.triggered"


ALL_INTELLIGENCE_EVENTS: frozenset[str] = frozenset([
    DAG_PROPOSED, DAG_VALIDATED, DAG_RESTRUCTURED,
    ASSUMPTION_RECORDED, ASSUMPTION_VALIDATED, ASSUMPTION_INVALIDATED,
    CHECKPOINT_TRIGGERED,
    MEMORY_CREATED, MEMORY_ACCESSED, MEMORY_REINFORCED,
    MEMORY_SUPERSEDED, MEMORY_CONFIDENCE_ADJUSTED,
    STRATEGY_RECOMMENDED, TRUST_PROMOTED, TRUST_DEMOTED, TRUST_DECAYED,
    RECOVERY_PLANNED, RECOVERY_SUCCEEDED, RECOVERY_FAILED,
    PATTERN_CREATED, PATTERN_RETIRED, ESCALATION_TRIGGERED,
])


def is_intelligence_event(event_type: str) -> bool:
    return event_type in ALL_INTELLIGENCE_EVENTS


EventPayload = dict[str, Any]


def dag_proposed_payload(
    objective: str,
    node_count: int,
    edge_count: int,
    assumption_count: int = 0,
) -> EventPayload:
    return {
        "objective": objective,
        "node_count": node_count,
        "edge_count": edge_count,
        "assumption_count": assumption_count,
    }


def memory_created_payload(
    memory_id: str,
    memory_type: str,
    content_preview: str,
    confidence: float,
    source: str = "",
) -> EventPayload:
    return {
        "memory_id": memory_id,
        "memory_type": memory_type,
        "content_preview": content_preview[:200],
        "confidence": confidence,
        "source": source,
    }


def recovery_planned_payload(
    failure_class: str,
    action: str,
    pattern_id: str | None = None,
    requires_approval: bool = True,
) -> EventPayload:
    return {
        "failure_class": failure_class,
        "action": action,
        "pattern_id": pattern_id,
        "requires_approval": requires_approval,
    }


def trust_change_payload(
    domain: str,
    old_level: str,
    new_level: str,
    score: float,
    reason: str = "",
) -> EventPayload:
    return {
        "domain": domain,
        "old_level": old_level,
        "new_level": new_level,
        "score": score,
        "reason": reason,
    }
