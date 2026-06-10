from __future__ import annotations

import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

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


class ConsensusEngine:
    """Multi-agent consensus protocol for critical decisions.

    Supports majority, supermajority, unanimous, weighted, and raft-like
    protocols with quorum enforcement and trust-weighted voting.
    """

    def __init__(self) -> None:
        self._participants: dict[str, Participant] = {}
        self._proposals: dict[str, Proposal] = {}
        self._votes: dict[str, list[Vote]] = defaultdict(list)
        self._decisions: list[ConsensusDecision] = []

    def add_participant(self, participant: Participant) -> None:
        self._participants[participant.participant_id] = participant

    def remove_participant(self, participant_id: str) -> bool:
        return self._participants.pop(participant_id, None) is not None

    def get_participant(self, participant_id: str) -> Participant | None:
        return self._participants.get(participant_id)

    def create_proposal(self, proposer_id: str, description: str,
                        protocol: ConsensusProtocol = ConsensusProtocol.MAJORITY,
                        quorum: float = 0.5, payload: dict[str, Any] | None = None,
                        timeout_ms: float = 30000.0) -> Proposal:
        proposal = Proposal(
            proposer_id=proposer_id,
            description=description,
            protocol=protocol,
            quorum=quorum,
            payload=payload or {},
            status=ProposalStatus.VOTING,
            timeout_ms=timeout_ms,
        )
        self._proposals[proposal.proposal_id] = proposal
        return proposal

    def cast_vote(self, participant_id: str, proposal_id: str,
                  value: VoteValue, reason: str = "", confidence: float = 1.0) -> Vote | None:
        if participant_id not in self._participants:
            return None
        proposal = self._proposals.get(proposal_id)
        if not proposal or proposal.status != ProposalStatus.VOTING:
            return None

        existing = [v for v in self._votes[proposal_id] if v.participant_id == participant_id]
        if existing:
            return None

        participant = self._participants[participant_id]
        if participant.role == ParticipantRole.OBSERVER:
            return None

        vote = Vote(
            participant_id=participant_id,
            proposal_id=proposal_id,
            value=value,
            reason=reason,
            confidence=confidence,
        )
        self._votes[proposal_id].append(vote)
        return vote

    def resolve(self, proposal_id: str) -> ConsensusDecision | None:
        proposal = self._proposals.get(proposal_id)
        if not proposal or proposal.status != ProposalStatus.VOTING:
            return None

        votes = self._votes.get(proposal_id, [])
        voters = [p for p in self._participants.values() if p.role != ParticipantRole.OBSERVER]

        if not voters:
            return self._finalize(proposal, False, votes, "No eligible voters")

        participation = len(votes) / len(voters) if voters else 0.0
        quorum_met = participation >= proposal.quorum

        if not quorum_met:
            return self._finalize(proposal, False, votes, "Quorum not met")

        accepted, reason = self._evaluate_protocol(proposal.protocol, votes, voters)
        return self._finalize(proposal, accepted, votes, reason)

    def get_proposal(self, proposal_id: str) -> Proposal | None:
        return self._proposals.get(proposal_id)

    def get_votes(self, proposal_id: str) -> list[Vote]:
        return list(self._votes.get(proposal_id, []))

    def cancel_proposal(self, proposal_id: str) -> bool:
        proposal = self._proposals.get(proposal_id)
        if not proposal or proposal.status != ProposalStatus.VOTING:
            return False
        self._proposals[proposal_id] = Proposal(
            proposal_id=proposal.proposal_id,
            proposer_id=proposal.proposer_id,
            description=proposal.description,
            payload=proposal.payload,
            protocol=proposal.protocol,
            status=ProposalStatus.CANCELLED,
            quorum=proposal.quorum,
            timeout_ms=proposal.timeout_ms,
            created_at=proposal.created_at,
            decided_at=datetime.now(UTC),
        )
        return True

    def get_stats(self) -> ConsensusStats:
        if not self._decisions:
            return ConsensusStats(total_proposals=len(self._proposals))

        accepted = sum(1 for d in self._decisions if d.accepted)
        rejected = sum(1 for d in self._decisions if not d.accepted)

        voters = [p for p in self._participants.values() if p.role != ParticipantRole.OBSERVER]
        total_voters = len(voters) if voters else 1
        avg_participation = 0.0
        if self._decisions:
            total_votes = sum(d.votes_for + d.votes_against + d.votes_abstain for d in self._decisions)
            avg_participation = total_votes / (len(self._decisions) * total_voters)

        return ConsensusStats(
            total_proposals=len(self._proposals),
            accepted=accepted,
            rejected=rejected,
            avg_participation=min(1.0, avg_participation),
        )

    def _evaluate_protocol(self, protocol: ConsensusProtocol,
                           votes: list[Vote], voters: list[Participant]) -> tuple[bool, str]:
        approve_count = sum(1 for v in votes if v.value == VoteValue.APPROVE)
        reject_count = sum(1 for v in votes if v.value == VoteValue.REJECT)
        total_cast = len(votes)

        if protocol == ConsensusProtocol.MAJORITY:
            accepted = approve_count > total_cast / 2
            return accepted, f"Majority: {approve_count}/{total_cast} approved"

        elif protocol == ConsensusProtocol.SUPERMAJORITY:
            threshold = total_cast * 2 / 3
            accepted = approve_count >= threshold
            return accepted, f"Supermajority: {approve_count}/{total_cast} (need {threshold:.0f})"

        elif protocol == ConsensusProtocol.UNANIMOUS:
            accepted = approve_count == total_cast and reject_count == 0
            return accepted, f"Unanimous: {approve_count}/{total_cast}"

        elif protocol == ConsensusProtocol.WEIGHTED:
            return self._weighted_vote(votes, voters)

        elif protocol == ConsensusProtocol.RAFT_LIKE:
            leaders = [p for p in voters if p.role == ParticipantRole.LEADER]
            if leaders:
                leader_votes = [v for v in votes if v.participant_id == leaders[0].participant_id]
                if leader_votes and leader_votes[0].value == VoteValue.APPROVE:
                    follower_approvals = sum(
                        1 for v in votes
                        if v.value == VoteValue.APPROVE and v.participant_id != leaders[0].participant_id
                    )
                    needed = (len(voters) - 1) // 2
                    accepted = follower_approvals >= needed
                    return accepted, f"Raft: leader approved, {follower_approvals} followers (need {needed})"
                return False, "Raft: leader did not approve"
            accepted = approve_count > total_cast / 2
            return accepted, f"Raft (no leader): majority {approve_count}/{total_cast}"

        return False, "Unknown protocol"

    def _weighted_vote(self, votes: list[Vote], voters: list[Participant]) -> tuple[bool, str]:
        weighted_for = 0.0
        weighted_against = 0.0

        for vote in votes:
            participant = self._participants.get(vote.participant_id)
            if not participant:
                continue
            weight = participant.weight * participant.trust_score * vote.confidence
            if vote.value == VoteValue.APPROVE:
                weighted_for += weight
            elif vote.value == VoteValue.REJECT:
                weighted_against += weight

        total_weight = weighted_for + weighted_against
        if total_weight == 0:
            return False, "Weighted: no decisive votes"

        accepted = weighted_for > weighted_against
        return accepted, f"Weighted: {weighted_for:.2f} for vs {weighted_against:.2f} against"

    def _finalize(self, proposal: Proposal, accepted: bool,
                  votes: list[Vote], reason: str) -> ConsensusDecision:
        approve_count = sum(1 for v in votes if v.value == VoteValue.APPROVE)
        reject_count = sum(1 for v in votes if v.value == VoteValue.REJECT)
        abstain_count = sum(1 for v in votes if v.value == VoteValue.ABSTAIN)

        voters = [p for p in self._participants.values() if p.role != ParticipantRole.OBSERVER]
        participation = len(votes) / len(voters) if voters else 0.0

        status = ProposalStatus.ACCEPTED if accepted else ProposalStatus.REJECTED
        self._proposals[proposal.proposal_id] = Proposal(
            proposal_id=proposal.proposal_id,
            proposer_id=proposal.proposer_id,
            description=proposal.description,
            payload=proposal.payload,
            protocol=proposal.protocol,
            status=status,
            quorum=proposal.quorum,
            timeout_ms=proposal.timeout_ms,
            created_at=proposal.created_at,
            decided_at=datetime.now(UTC),
        )

        decision = ConsensusDecision(
            proposal_id=proposal.proposal_id,
            accepted=accepted,
            votes_for=approve_count,
            votes_against=reject_count,
            votes_abstain=abstain_count,
            weighted_score=approve_count / len(votes) if votes else 0.0,
            quorum_met=participation >= proposal.quorum,
            protocol_used=proposal.protocol,
            reason=reason,
        )
        self._decisions.append(decision)
        return decision
