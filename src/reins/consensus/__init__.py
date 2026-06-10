"""Multi-Agent Consensus: fault-tolerant agreement protocols for critical agent decisions."""

from reins.consensus.engine import ConsensusEngine
from reins.consensus.types import (
    ConsensusDecision,
    ConsensusProtocol,
    ConsensusStats,
    Participant,
    ParticipantRole,
    Proposal,
    ProposalStatus,
    Vote,
    VoteValue,
)

__all__ = [
    "ConsensusDecision",
    "ConsensusEngine",
    "ConsensusProtocol",
    "ConsensusStats",
    "Participant",
    "ParticipantRole",
    "Proposal",
    "ProposalStatus",
    "Vote",
    "VoteValue",
]
