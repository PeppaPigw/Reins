"""Tests for multi-agent consensus engine."""

from __future__ import annotations

import pytest

from reins.consensus import (
    ConsensusDecision,
    ConsensusEngine,
    ConsensusProtocol,
    ConsensusStats,
    Participant,
    ParticipantRole,
    Proposal,
    ProposalStatus,
    Vote,
    VoteValue,
)


@pytest.fixture
def engine() -> ConsensusEngine:
    eng = ConsensusEngine()
    eng.add_participant(Participant(participant_id="a1", role=ParticipantRole.VOTER, weight=1.0))
    eng.add_participant(Participant(participant_id="a2", role=ParticipantRole.VOTER, weight=1.0))
    eng.add_participant(Participant(participant_id="a3", role=ParticipantRole.VOTER, weight=1.0))
    return eng


def test_add_and_get_participant(engine):
    p = engine.get_participant("a1")
    assert p is not None
    assert p.participant_id == "a1"


def test_remove_participant(engine):
    assert engine.remove_participant("a1")
    assert engine.get_participant("a1") is None


def test_remove_nonexistent(engine):
    assert not engine.remove_participant("nonexistent")


def test_create_proposal(engine):
    proposal = engine.create_proposal("a1", "deploy v2")
    assert proposal.status == ProposalStatus.VOTING
    assert proposal.proposer_id == "a1"


def test_cast_vote(engine):
    proposal = engine.create_proposal("a1", "deploy v2")
    vote = engine.cast_vote("a2", proposal.proposal_id, VoteValue.APPROVE)
    assert vote is not None
    assert vote.value == VoteValue.APPROVE


def test_cast_vote_nonexistent_participant(engine):
    proposal = engine.create_proposal("a1", "deploy v2")
    vote = engine.cast_vote("unknown", proposal.proposal_id, VoteValue.APPROVE)
    assert vote is None


def test_cast_vote_nonexistent_proposal(engine):
    vote = engine.cast_vote("a1", "nonexistent", VoteValue.APPROVE)
    assert vote is None


def test_duplicate_vote_rejected(engine):
    proposal = engine.create_proposal("a1", "deploy v2")
    engine.cast_vote("a2", proposal.proposal_id, VoteValue.APPROVE)
    dup = engine.cast_vote("a2", proposal.proposal_id, VoteValue.REJECT)
    assert dup is None


def test_observer_cannot_vote(engine):
    engine.add_participant(Participant(participant_id="obs", role=ParticipantRole.OBSERVER))
    proposal = engine.create_proposal("a1", "deploy v2")
    vote = engine.cast_vote("obs", proposal.proposal_id, VoteValue.APPROVE)
    assert vote is None


def test_majority_accepts(engine):
    proposal = engine.create_proposal("a1", "deploy v2")
    engine.cast_vote("a1", proposal.proposal_id, VoteValue.APPROVE)
    engine.cast_vote("a2", proposal.proposal_id, VoteValue.APPROVE)
    engine.cast_vote("a3", proposal.proposal_id, VoteValue.REJECT)

    decision = engine.resolve(proposal.proposal_id)
    assert decision is not None
    assert decision.accepted
    assert decision.votes_for == 2
    assert decision.votes_against == 1


def test_majority_rejects(engine):
    proposal = engine.create_proposal("a1", "deploy v2")
    engine.cast_vote("a1", proposal.proposal_id, VoteValue.REJECT)
    engine.cast_vote("a2", proposal.proposal_id, VoteValue.REJECT)
    engine.cast_vote("a3", proposal.proposal_id, VoteValue.APPROVE)

    decision = engine.resolve(proposal.proposal_id)
    assert not decision.accepted


def test_supermajority_requires_two_thirds(engine):
    proposal = engine.create_proposal("a1", "critical change", protocol=ConsensusProtocol.SUPERMAJORITY)
    engine.cast_vote("a1", proposal.proposal_id, VoteValue.APPROVE)
    engine.cast_vote("a2", proposal.proposal_id, VoteValue.APPROVE)
    engine.cast_vote("a3", proposal.proposal_id, VoteValue.REJECT)

    decision = engine.resolve(proposal.proposal_id)
    assert decision.accepted  # 2/3 = 0.666, need >= 0.666


def test_supermajority_fails_below_threshold(engine):
    engine.add_participant(Participant(participant_id="a4", role=ParticipantRole.VOTER))
    proposal = engine.create_proposal("a1", "critical", protocol=ConsensusProtocol.SUPERMAJORITY)
    engine.cast_vote("a1", proposal.proposal_id, VoteValue.APPROVE)
    engine.cast_vote("a2", proposal.proposal_id, VoteValue.APPROVE)
    engine.cast_vote("a3", proposal.proposal_id, VoteValue.REJECT)
    engine.cast_vote("a4", proposal.proposal_id, VoteValue.REJECT)

    decision = engine.resolve(proposal.proposal_id)
    assert not decision.accepted  # 2/4 < 2/3


def test_unanimous_requires_all(engine):
    proposal = engine.create_proposal("a1", "unanimous", protocol=ConsensusProtocol.UNANIMOUS)
    engine.cast_vote("a1", proposal.proposal_id, VoteValue.APPROVE)
    engine.cast_vote("a2", proposal.proposal_id, VoteValue.APPROVE)
    engine.cast_vote("a3", proposal.proposal_id, VoteValue.APPROVE)

    decision = engine.resolve(proposal.proposal_id)
    assert decision.accepted


def test_unanimous_fails_with_one_reject(engine):
    proposal = engine.create_proposal("a1", "unanimous", protocol=ConsensusProtocol.UNANIMOUS)
    engine.cast_vote("a1", proposal.proposal_id, VoteValue.APPROVE)
    engine.cast_vote("a2", proposal.proposal_id, VoteValue.APPROVE)
    engine.cast_vote("a3", proposal.proposal_id, VoteValue.REJECT)

    decision = engine.resolve(proposal.proposal_id)
    assert not decision.accepted


def test_weighted_voting(engine):
    engine.add_participant(Participant(participant_id="heavy", role=ParticipantRole.VOTER, weight=5.0))
    proposal = engine.create_proposal("a1", "weighted", protocol=ConsensusProtocol.WEIGHTED)
    engine.cast_vote("a1", proposal.proposal_id, VoteValue.REJECT)
    engine.cast_vote("a2", proposal.proposal_id, VoteValue.REJECT)
    engine.cast_vote("a3", proposal.proposal_id, VoteValue.REJECT)
    engine.cast_vote("heavy", proposal.proposal_id, VoteValue.APPROVE)

    decision = engine.resolve(proposal.proposal_id)
    assert decision.accepted  # weight 5 > 3


def test_raft_like_leader_approve(engine):
    engine.add_participant(Participant(participant_id="leader", role=ParticipantRole.LEADER))
    proposal = engine.create_proposal("a1", "raft", protocol=ConsensusProtocol.RAFT_LIKE)
    engine.cast_vote("leader", proposal.proposal_id, VoteValue.APPROVE)
    engine.cast_vote("a1", proposal.proposal_id, VoteValue.APPROVE)
    engine.cast_vote("a2", proposal.proposal_id, VoteValue.REJECT)
    engine.cast_vote("a3", proposal.proposal_id, VoteValue.REJECT)

    decision = engine.resolve(proposal.proposal_id)
    # leader approved + 1 follower >= (4-1)//2 = 1 needed
    assert decision.accepted


def test_raft_like_leader_reject(engine):
    engine.add_participant(Participant(participant_id="leader", role=ParticipantRole.LEADER))
    proposal = engine.create_proposal("a1", "raft", protocol=ConsensusProtocol.RAFT_LIKE)
    engine.cast_vote("leader", proposal.proposal_id, VoteValue.REJECT)
    engine.cast_vote("a1", proposal.proposal_id, VoteValue.APPROVE)
    engine.cast_vote("a2", proposal.proposal_id, VoteValue.APPROVE)
    engine.cast_vote("a3", proposal.proposal_id, VoteValue.APPROVE)

    decision = engine.resolve(proposal.proposal_id)
    assert not decision.accepted


def test_quorum_not_met(engine):
    proposal = engine.create_proposal("a1", "quorum test", quorum=0.8)
    engine.cast_vote("a1", proposal.proposal_id, VoteValue.APPROVE)

    decision = engine.resolve(proposal.proposal_id)
    assert not decision.accepted
    assert "Quorum" in decision.reason


def test_resolve_already_decided(engine):
    proposal = engine.create_proposal("a1", "test")
    engine.cast_vote("a1", proposal.proposal_id, VoteValue.APPROVE)
    engine.cast_vote("a2", proposal.proposal_id, VoteValue.APPROVE)
    engine.resolve(proposal.proposal_id)

    second = engine.resolve(proposal.proposal_id)
    assert second is None


def test_cancel_proposal(engine):
    proposal = engine.create_proposal("a1", "cancel me")
    assert engine.cancel_proposal(proposal.proposal_id)
    updated = engine.get_proposal(proposal.proposal_id)
    assert updated.status == ProposalStatus.CANCELLED


def test_cancel_already_decided(engine):
    proposal = engine.create_proposal("a1", "test")
    engine.cast_vote("a1", proposal.proposal_id, VoteValue.APPROVE)
    engine.cast_vote("a2", proposal.proposal_id, VoteValue.APPROVE)
    engine.resolve(proposal.proposal_id)
    assert not engine.cancel_proposal(proposal.proposal_id)


def test_get_votes(engine):
    proposal = engine.create_proposal("a1", "test")
    engine.cast_vote("a1", proposal.proposal_id, VoteValue.APPROVE)
    engine.cast_vote("a2", proposal.proposal_id, VoteValue.REJECT)

    votes = engine.get_votes(proposal.proposal_id)
    assert len(votes) == 2


def test_abstain_counted(engine):
    proposal = engine.create_proposal("a1", "test")
    engine.cast_vote("a1", proposal.proposal_id, VoteValue.APPROVE)
    engine.cast_vote("a2", proposal.proposal_id, VoteValue.ABSTAIN)
    engine.cast_vote("a3", proposal.proposal_id, VoteValue.ABSTAIN)

    decision = engine.resolve(proposal.proposal_id)
    assert decision.votes_abstain == 2
    # 1 approve out of 3 total is not majority
    assert not decision.accepted


def test_stats_empty():
    eng = ConsensusEngine()
    stats = eng.get_stats()
    assert stats.total_proposals == 0
    assert stats.accepted == 0


def test_stats_after_decisions(engine):
    p1 = engine.create_proposal("a1", "accept me")
    engine.cast_vote("a1", p1.proposal_id, VoteValue.APPROVE)
    engine.cast_vote("a2", p1.proposal_id, VoteValue.APPROVE)
    engine.cast_vote("a3", p1.proposal_id, VoteValue.APPROVE)
    engine.resolve(p1.proposal_id)

    p2 = engine.create_proposal("a1", "reject me")
    engine.cast_vote("a1", p2.proposal_id, VoteValue.REJECT)
    engine.cast_vote("a2", p2.proposal_id, VoteValue.REJECT)
    engine.cast_vote("a3", p2.proposal_id, VoteValue.REJECT)
    engine.resolve(p2.proposal_id)

    stats = engine.get_stats()
    assert stats.total_proposals == 2
    assert stats.accepted == 1
    assert stats.rejected == 1


def test_trust_score_affects_weighted(engine):
    engine.add_participant(Participant(
        participant_id="untrusted", role=ParticipantRole.VOTER, weight=10.0, trust_score=0.1
    ))
    proposal = engine.create_proposal("a1", "trust test", protocol=ConsensusProtocol.WEIGHTED)
    engine.cast_vote("a1", proposal.proposal_id, VoteValue.REJECT)
    engine.cast_vote("a2", proposal.proposal_id, VoteValue.REJECT)
    engine.cast_vote("a3", proposal.proposal_id, VoteValue.REJECT)
    engine.cast_vote("untrusted", proposal.proposal_id, VoteValue.APPROVE)

    decision = engine.resolve(proposal.proposal_id)
    # untrusted: 10 * 0.1 = 1.0 effective weight, vs 3 * 1.0 = 3.0 against
    assert not decision.accepted


def test_confidence_affects_weighted(engine):
    proposal = engine.create_proposal("a1", "confidence", protocol=ConsensusProtocol.WEIGHTED)
    engine.cast_vote("a1", proposal.proposal_id, VoteValue.APPROVE, confidence=0.1)
    engine.cast_vote("a2", proposal.proposal_id, VoteValue.REJECT, confidence=1.0)
    engine.cast_vote("a3", proposal.proposal_id, VoteValue.REJECT, confidence=1.0)

    decision = engine.resolve(proposal.proposal_id)
    assert not decision.accepted
