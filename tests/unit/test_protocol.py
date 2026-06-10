"""Tests for formal inter-agent protocol engine."""

from __future__ import annotations

import pytest

from reins.protocol import (
    CapabilityOffer,
    Channel,
    ChannelState,
    MessageKind,
    NegotiationRecord,
    NegotiationStatus,
    ProtocolEngine,
    ProtocolMessage,
    ProtocolStats,
)


@pytest.fixture
def engine() -> ProtocolEngine:
    return ProtocolEngine()


def test_register_capabilities(engine):
    offer = engine.register_capabilities("agent-1",
                                          capabilities=["code_review", "testing"],
                                          max_concurrency=3)
    assert offer.agent_id == "agent-1"
    assert "code_review" in offer.capabilities
    assert offer.max_concurrency == 3


def test_get_capabilities(engine):
    engine.register_capabilities("a", capabilities=["x"])
    assert engine.get_capabilities("a") is not None
    assert engine.get_capabilities("missing") is None


def test_open_channel(engine):
    ch = engine.open_channel("a", "b")
    assert ch.agent_a == "a"
    assert ch.agent_b == "b"
    assert ch.state == ChannelState.OPEN


def test_close_channel(engine):
    ch = engine.open_channel("a", "b")
    closed = engine.close_channel(ch.channel_id)
    assert closed.state == ChannelState.CLOSED


def test_close_nonexistent(engine):
    assert engine.close_channel("missing") is None


def test_negotiate_capabilities(engine):
    engine.register_capabilities("responder", capabilities=["analyze", "summarize"])
    record = engine.negotiate("initiator", "responder",
                              requested_capabilities=["analyze"])
    assert record.status == NegotiationStatus.PROPOSED
    assert record.initiator == "initiator"


def test_accept_negotiation(engine):
    engine.register_capabilities("b", capabilities=["code", "test", "deploy"])
    record = engine.negotiate("a", "b", requested_capabilities=["code", "test"])
    accepted = engine.accept_negotiation(record.negotiation_id)
    assert accepted.status == NegotiationStatus.ACCEPTED
    assert set(accepted.accepted_capabilities) == {"code", "test"}


def test_accept_partial_capabilities(engine):
    engine.register_capabilities("b", capabilities=["code"])
    record = engine.negotiate("a", "b", requested_capabilities=["code", "deploy"])
    accepted = engine.accept_negotiation(record.negotiation_id)
    assert accepted.status == NegotiationStatus.ACCEPTED
    assert accepted.accepted_capabilities == ["code"]


def test_accept_no_overlap_rejects(engine):
    engine.register_capabilities("b", capabilities=["code"])
    record = engine.negotiate("a", "b", requested_capabilities=["deploy"])
    result = engine.accept_negotiation(record.negotiation_id)
    assert result.status == NegotiationStatus.REJECTED


def test_accept_no_offer_rejects(engine):
    record = engine.negotiate("a", "b", requested_capabilities=["x"])
    result = engine.accept_negotiation(record.negotiation_id)
    assert result.status == NegotiationStatus.REJECTED


def test_accept_nonexistent(engine):
    assert engine.accept_negotiation("missing") is None


def test_reject_negotiation(engine):
    record = engine.negotiate("a", "b", requested_capabilities=["x"])
    rejected = engine.reject_negotiation(record.negotiation_id)
    assert rejected.status == NegotiationStatus.REJECTED


def test_reject_nonexistent(engine):
    assert engine.reject_negotiation("missing") is None


def test_send_message(engine):
    msg = engine.send("a", "b", MessageKind.REQUEST,
                      payload={"task": "review code"})
    assert msg.sender == "a"
    assert msg.kind == MessageKind.REQUEST
    assert msg.payload["task"] == "review code"


def test_send_with_channel(engine):
    ch = engine.open_channel("a", "b")
    engine.send("a", "b", MessageKind.REQUEST, channel_id=ch.channel_id)
    engine.send("b", "a", MessageKind.RESPONSE, channel_id=ch.channel_id)
    updated = engine.get_channel(ch.channel_id)
    assert updated.messages_sent == 2


def test_send_with_correlation(engine):
    req = engine.send("a", "b", MessageKind.REQUEST)
    resp = engine.send("b", "a", MessageKind.RESPONSE,
                       correlation_id=req.message_id)
    assert resp.correlation_id == req.message_id


def test_get_messages_filter_sender(engine):
    engine.send("a", "b", MessageKind.REQUEST)
    engine.send("c", "b", MessageKind.REQUEST)
    assert len(engine.get_messages(sender="a")) == 1


def test_get_messages_filter_receiver(engine):
    engine.send("a", "b", MessageKind.REQUEST)
    engine.send("a", "c", MessageKind.NOTIFY)
    assert len(engine.get_messages(receiver="b")) == 1


def test_get_messages_filter_kind(engine):
    engine.send("a", "b", MessageKind.REQUEST)
    engine.send("a", "b", MessageKind.HEARTBEAT)
    assert len(engine.get_messages(kind=MessageKind.HEARTBEAT)) == 1


def test_get_negotiation(engine):
    record = engine.negotiate("a", "b", requested_capabilities=["x"])
    assert engine.get_negotiation(record.negotiation_id) is not None
    assert engine.get_negotiation("missing") is None


def test_stats_empty(engine):
    stats = engine.get_stats()
    assert stats.total_messages == 0
    assert stats.total_channels == 0


def test_stats_populated(engine):
    engine.register_capabilities("b", capabilities=["x"])
    ch = engine.open_channel("a", "b")
    engine.send("a", "b", MessageKind.REQUEST, channel_id=ch.channel_id)
    engine.send("b", "a", MessageKind.RESPONSE, channel_id=ch.channel_id)
    n = engine.negotiate("a", "b", requested_capabilities=["x"])
    engine.accept_negotiation(n.negotiation_id)
    stats = engine.get_stats()
    assert stats.total_messages == 2
    assert stats.total_channels == 1
    assert stats.active_channels == 1
    assert stats.total_negotiations == 1
    assert stats.successful_negotiations == 1
    assert stats.by_kind["request"] == 1
    assert stats.by_kind["response"] == 1


def test_all_message_kinds(engine):
    for kind in MessageKind:
        engine.send("a", "b", kind)
    assert len(engine.get_messages()) == len(MessageKind)
