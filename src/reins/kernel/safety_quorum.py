"""Safety Quorum: bridges reactive mesh escalations to consensus-based decisions."""

from __future__ import annotations

from typing import Any

from reins.consensus import (
    ConsensusDecision,
    ConsensusEngine,
    ConsensusProtocol,
    Participant,
    ParticipantRole,
    VoteValue,
)
from reins.event_bus import EventBus
from reins.reactive_mesh import Reaction, ReactionKind


class SafetyQuorum:
    """Requires multi-agent consensus before allowing escalated actions.

    When the reactive mesh escalates a decision, the quorum collects votes
    from registered safety agents and resolves based on the configured protocol.
    """

    def __init__(self, bus: EventBus,
                 protocol: ConsensusProtocol = ConsensusProtocol.MAJORITY,
                 quorum: float = 0.5) -> None:
        self._bus = bus
        self._consensus = ConsensusEngine()
        self._protocol = protocol
        self._quorum = quorum
        self._pending: dict[str, str] = {}  # proposal_id -> agent_id

    def register_voter(self, voter_id: str, weight: float = 1.0) -> None:
        self._consensus.add_participant(Participant(
            participant_id=voter_id, role=ParticipantRole.VOTER, weight=weight,
        ))

    def propose_action(self, agent_id: str, action: str,
                       context: dict[str, Any] | None = None) -> str:
        proposal = self._consensus.create_proposal(
            proposer_id=agent_id,
            description=f"Allow '{action}' for agent '{agent_id}'",
            protocol=self._protocol,
            quorum=self._quorum,
            payload={"agent_id": agent_id, "action": action, **(context or {})},
        )
        self._pending[proposal.proposal_id] = agent_id
        self._bus.publish_sync("quorum.proposed", "safety-quorum",
                               {"proposal_id": proposal.proposal_id, "agent_id": agent_id, "action": action})
        return proposal.proposal_id

    def vote(self, voter_id: str, proposal_id: str, approve: bool, reason: str = "") -> bool:
        value = VoteValue.APPROVE if approve else VoteValue.REJECT
        vote = self._consensus.cast_vote(voter_id, proposal_id, value, reason=reason)
        return vote is not None

    def resolve(self, proposal_id: str) -> ConsensusDecision | None:
        decision = self._consensus.resolve(proposal_id)
        if decision:
            agent_id = self._pending.pop(proposal_id, "unknown")
            topic = "quorum.accepted" if decision.accepted else "quorum.rejected"
            self._bus.publish_sync(topic, "safety-quorum",
                                   {"proposal_id": proposal_id, "agent_id": agent_id,
                                    "votes_for": decision.votes_for, "votes_against": decision.votes_against})
        return decision

    def handle_escalation(self, reaction: Reaction) -> str:
        agent_id = reaction.agent_id
        action = reaction.payload.get("action", "unknown")
        return self.propose_action(agent_id, action, reaction.payload)

    @property
    def consensus(self) -> ConsensusEngine:
        return self._consensus
