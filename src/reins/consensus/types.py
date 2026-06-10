from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

import ulid
from pydantic import BaseModel, ConfigDict, Field


def _new_ulid() -> str:
    return str(ulid.new())


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ConsensusProtocol(str, Enum):
    MAJORITY = "majority"
    SUPERMAJORITY = "supermajority"
    UNANIMOUS = "unanimous"
    WEIGHTED = "weighted"
    RAFT_LIKE = "raft_like"


class VoteValue(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    ABSTAIN = "abstain"


class ProposalStatus(str, Enum):
    PENDING = "pending"
    VOTING = "voting"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ParticipantRole(str, Enum):
    VOTER = "voter"
    PROPOSER = "proposer"
    OBSERVER = "observer"
    LEADER = "leader"


class Participant(BaseModel):
    model_config = ConfigDict(frozen=True)

    participant_id: str
    role: ParticipantRole = ParticipantRole.VOTER
    weight: float = 1.0
    trust_score: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class Vote(BaseModel):
    model_config = ConfigDict(frozen=True)

    vote_id: str = Field(default_factory=_new_ulid)
    participant_id: str
    proposal_id: str
    value: VoteValue
    reason: str = ""
    confidence: float = 1.0
    timestamp: datetime = Field(default_factory=_utc_now)


class Proposal(BaseModel):
    model_config = ConfigDict(frozen=True)

    proposal_id: str = Field(default_factory=_new_ulid)
    proposer_id: str
    description: str
    payload: dict[str, Any] = Field(default_factory=dict)
    protocol: ConsensusProtocol = ConsensusProtocol.MAJORITY
    status: ProposalStatus = ProposalStatus.PENDING
    quorum: float = 0.5
    timeout_ms: float = 30000.0
    created_at: datetime = Field(default_factory=_utc_now)
    decided_at: datetime | None = None


class ConsensusDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_id: str = Field(default_factory=_new_ulid)
    proposal_id: str
    accepted: bool
    votes_for: int = 0
    votes_against: int = 0
    votes_abstain: int = 0
    weighted_score: float = 0.0
    quorum_met: bool = False
    protocol_used: ConsensusProtocol = ConsensusProtocol.MAJORITY
    reason: str = ""
    decided_at: datetime = Field(default_factory=_utc_now)


class ConsensusStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_proposals: int = 0
    accepted: int = 0
    rejected: int = 0
    expired: int = 0
    avg_participation: float = 0.0
    avg_time_to_decision_ms: float = 0.0
