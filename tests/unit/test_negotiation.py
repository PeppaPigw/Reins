"""Tests for negotiation protocol with multi-agent resource allocation."""

from __future__ import annotations

import pytest

from reins.negotiation import (
    Agreement,
    Negotiation,
    NegotiationEngine,
    NegotiationStats,
    NegotiationStatus,
    Offer,
    OfferKind,
    ResolutionStrategy,
)


@pytest.fixture
def engine() -> NegotiationEngine:
    return NegotiationEngine(default_max_rounds=5)


def test_initiate_negotiation(engine):
    neg = engine.initiate("alice", "bob", OfferKind.RESOURCE, initial_value=100.0)
    assert neg.status == NegotiationStatus.OPEN
    assert neg.initiator == "alice"
    assert neg.responder == "bob"
    assert len(neg.offers) == 1
    assert neg.offers[0].value == 100.0


def test_get_negotiation(engine):
    neg = engine.initiate("alice", "bob", OfferKind.RESOURCE)
    retrieved = engine.get_negotiation(neg.negotiation_id)
    assert retrieved is not None
    assert retrieved.negotiation_id == neg.negotiation_id


def test_get_negotiation_not_found(engine):
    assert engine.get_negotiation("nonexistent") is None


def test_counter_offer(engine):
    neg = engine.initiate("alice", "bob", OfferKind.RESOURCE, initial_value=100.0)
    counter = engine.counter_offer(neg.negotiation_id, "bob", value=80.0)
    assert counter is not None
    assert counter.is_counter is True
    assert counter.value == 80.0
    assert counter.from_agent == "bob"


def test_counter_offer_updates_status(engine):
    neg = engine.initiate("alice", "bob", OfferKind.RESOURCE, initial_value=100.0)
    engine.counter_offer(neg.negotiation_id, "bob", value=80.0)
    updated = engine.get_negotiation(neg.negotiation_id)
    assert updated.status == NegotiationStatus.COUNTER_OFFERED
    assert updated.current_round == 2


def test_counter_offer_nonexistent(engine):
    assert engine.counter_offer("nonexistent", "bob", 50.0) is None


def test_counter_offer_after_accept(engine):
    neg = engine.initiate("alice", "bob", OfferKind.RESOURCE, initial_value=100.0)
    engine.accept(neg.negotiation_id, "bob")
    assert engine.counter_offer(neg.negotiation_id, "bob", 80.0) is None


def test_deadlock_on_max_rounds(engine):
    eng = NegotiationEngine(default_max_rounds=2)
    neg = eng.initiate("alice", "bob", OfferKind.RESOURCE, initial_value=100.0)
    eng.counter_offer(neg.negotiation_id, "bob", value=50.0)
    result = eng.counter_offer(neg.negotiation_id, "alice", value=75.0)
    assert result is None
    updated = eng.get_negotiation(neg.negotiation_id)
    assert updated.status == NegotiationStatus.DEADLOCKED


def test_accept_negotiation(engine):
    neg = engine.initiate("alice", "bob", OfferKind.RESOURCE, initial_value=100.0)
    agreement = engine.accept(neg.negotiation_id, "bob")
    assert agreement is not None
    assert agreement.final_value == 100.0
    assert "alice" in agreement.parties
    assert "bob" in agreement.parties


def test_accept_sets_status(engine):
    neg = engine.initiate("alice", "bob", OfferKind.RESOURCE, initial_value=100.0)
    engine.accept(neg.negotiation_id, "bob")
    updated = engine.get_negotiation(neg.negotiation_id)
    assert updated.status == NegotiationStatus.ACCEPTED


def test_accept_nonexistent(engine):
    assert engine.accept("nonexistent", "bob") is None


def test_accept_already_resolved(engine):
    neg = engine.initiate("alice", "bob", OfferKind.RESOURCE, initial_value=100.0)
    engine.reject(neg.negotiation_id)
    assert engine.accept(neg.negotiation_id, "bob") is None


def test_reject_negotiation(engine):
    neg = engine.initiate("alice", "bob", OfferKind.RESOURCE, initial_value=100.0)
    assert engine.reject(neg.negotiation_id)
    updated = engine.get_negotiation(neg.negotiation_id)
    assert updated.status == NegotiationStatus.REJECTED


def test_reject_nonexistent(engine):
    assert not engine.reject("nonexistent")


def test_reject_already_resolved(engine):
    neg = engine.initiate("alice", "bob", OfferKind.RESOURCE, initial_value=100.0)
    engine.accept(neg.negotiation_id, "bob")
    assert not engine.reject(neg.negotiation_id)


def test_split_difference(engine):
    neg = engine.initiate("alice", "bob", OfferKind.RESOURCE, initial_value=100.0)
    engine.counter_offer(neg.negotiation_id, "bob", value=60.0)
    agreement = engine.split_difference(neg.negotiation_id)
    assert agreement is not None
    assert agreement.final_value == pytest.approx(80.0)


def test_split_difference_insufficient_offers(engine):
    neg = engine.initiate("alice", "bob", OfferKind.RESOURCE, initial_value=100.0)
    assert engine.split_difference(neg.negotiation_id) is None


def test_split_difference_nonexistent(engine):
    assert engine.split_difference("nonexistent") is None


def test_get_agreements_all(engine):
    neg = engine.initiate("alice", "bob", OfferKind.RESOURCE, initial_value=100.0)
    engine.accept(neg.negotiation_id, "bob")
    agreements = engine.get_agreements()
    assert len(agreements) == 1


def test_get_agreements_by_agent(engine):
    n1 = engine.initiate("alice", "bob", OfferKind.RESOURCE, initial_value=100.0)
    n2 = engine.initiate("charlie", "dave", OfferKind.TASK_ASSIGNMENT, initial_value=50.0)
    engine.accept(n1.negotiation_id, "bob")
    engine.accept(n2.negotiation_id, "dave")
    agreements = engine.get_agreements(agent_id="alice")
    assert len(agreements) == 1


def test_get_active_negotiations(engine):
    n1 = engine.initiate("alice", "bob", OfferKind.RESOURCE, initial_value=100.0)
    n2 = engine.initiate("charlie", "dave", OfferKind.TASK_ASSIGNMENT, initial_value=50.0)
    engine.accept(n1.negotiation_id, "bob")
    active = engine.get_active_negotiations()
    assert len(active) == 1
    assert active[0].negotiation_id == n2.negotiation_id


def test_get_active_negotiations_by_agent(engine):
    engine.initiate("alice", "bob", OfferKind.RESOURCE, initial_value=100.0)
    engine.initiate("alice", "charlie", OfferKind.TIME_SLOT, initial_value=30.0)
    engine.initiate("dave", "eve", OfferKind.RESOURCE, initial_value=20.0)
    active = engine.get_active_negotiations(agent_id="alice")
    assert len(active) == 2


def test_terms_preserved_in_offer(engine):
    neg = engine.initiate("alice", "bob", OfferKind.RESOURCE, initial_value=100.0,
                          terms={"cpu_cores": 4, "memory_gb": 16})
    assert neg.offers[0].terms == {"cpu_cores": 4, "memory_gb": 16}


def test_terms_in_agreement(engine):
    neg = engine.initiate("alice", "bob", OfferKind.RESOURCE, initial_value=100.0,
                          terms={"cpu_cores": 4})
    agreement = engine.accept(neg.negotiation_id, "bob")
    assert agreement.terms == {"cpu_cores": 4}


def test_multiple_counter_offers(engine):
    neg = engine.initiate("alice", "bob", OfferKind.RESOURCE, initial_value=100.0)
    engine.counter_offer(neg.negotiation_id, "bob", value=60.0)
    engine.counter_offer(neg.negotiation_id, "alice", value=80.0)
    engine.counter_offer(neg.negotiation_id, "bob", value=70.0)
    updated = engine.get_negotiation(neg.negotiation_id)
    assert len(updated.offers) == 4
    assert updated.current_round == 4


def test_stats_empty():
    eng = NegotiationEngine()
    stats = eng.get_stats()
    assert stats.total_negotiations == 0
    assert stats.agreement_rate == 0.0


def test_stats_with_data(engine):
    n1 = engine.initiate("alice", "bob", OfferKind.RESOURCE, initial_value=100.0)
    n2 = engine.initiate("charlie", "dave", OfferKind.TASK_ASSIGNMENT, initial_value=50.0)
    engine.accept(n1.negotiation_id, "bob")
    engine.reject(n2.negotiation_id)
    stats = engine.get_stats()
    assert stats.total_negotiations == 2
    assert stats.accepted == 1
    assert stats.rejected == 1
    assert stats.agreement_rate == pytest.approx(0.5)
    assert OfferKind.RESOURCE.value in stats.by_kind


def test_offer_kind_types(engine):
    for kind in OfferKind:
        neg = engine.initiate("a", "b", kind, initial_value=10.0)
        assert neg.kind == kind


def test_resolution_strategy_stored(engine):
    neg = engine.initiate("a", "b", OfferKind.RESOURCE,
                          strategy=ResolutionStrategy.SPLIT_DIFFERENCE)
    assert neg.strategy == ResolutionStrategy.SPLIT_DIFFERENCE
