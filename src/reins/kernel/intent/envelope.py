from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import ulid

from reins.kernel.types import ArtifactRef, RiskTier


class IntentIssuer(str, Enum):
    user = "user"
    scheduler = "scheduler"
    webhook = "webhook"
    remote_agent = "remote_agent"


@dataclass(frozen=True)
class IntentEnvelope:
    run_id: str
    objective: str
    issuer: IntentIssuer = IntentIssuer.user
    constraints: list[str] = field(default_factory=list)
    attachments: list[ArtifactRef] = field(default_factory=list)
    requested_capabilities: list[str] = field(default_factory=list)
    intent_id: str = field(default_factory=lambda: str(ulid.new()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class CommandProposal:
    run_id: str
    source: str
    kind: str
    args: dict[str, Any] = field(default_factory=dict)
    rationale_ref: str | None = None
    confidence: float = 0.0
    risk_tier_hint: RiskTier | None = None
    idempotency_key: str | None = None
    proposal_id: str = field(default_factory=lambda: str(ulid.new()))


@dataclass(frozen=True)
class CommandEnvelope:
    run_id: str
    normalized_kind: str
    args: dict[str, Any] = field(default_factory=dict)
    parent_proposal_id: str | None = None
    preconditions: dict[str, Any] = field(default_factory=dict)
    policy_scope: dict[str, Any] = field(default_factory=dict)
    risk_tier: RiskTier = RiskTier.T0
    idempotency_key: str | None = None
    evidence_refs: list[str] = field(default_factory=list)
    command_id: str = field(default_factory=lambda: str(ulid.new()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
