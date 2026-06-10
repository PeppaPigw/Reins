"""Tests for agent collaboration protocol."""

from __future__ import annotations

import pytest

from reins.collaboration import (
    Channel,
    ChannelKind,
    ChannelStats,
    CollaborationBus,
    Delivery,
    DeliveryStatus,
    Message,
    MessagePriority,
    Subscription,
    SubscriptionStatus,
)


@pytest.fixture
def bus() -> CollaborationBus:
    return CollaborationBus()


def test_create_channel(bus):
    ch = bus.create_channel("events", ChannelKind.PUBSUB)
    assert ch.name == "events"
    assert ch.kind == ChannelKind.PUBSUB


def test_get_channel(bus):
    ch = bus.create_channel("events", ChannelKind.PUBSUB)
    retrieved = bus.get_channel(ch.channel_id)
    assert retrieved is not None
    assert retrieved.name == "events"


def test_get_channel_nonexistent(bus):
    assert bus.get_channel("nonexistent") is None


def test_subscribe(bus):
    ch = bus.create_channel("events", ChannelKind.PUBSUB)
    sub = bus.subscribe(ch.channel_id, "agent-1")
    assert sub is not None
    assert sub.subscriber_id == "agent-1"
    assert sub.status == SubscriptionStatus.ACTIVE


def test_subscribe_nonexistent_channel(bus):
    assert bus.subscribe("nonexistent", "agent-1") is None


def test_subscribe_duplicate_returns_existing(bus):
    ch = bus.create_channel("events", ChannelKind.PUBSUB)
    sub1 = bus.subscribe(ch.channel_id, "agent-1")
    sub2 = bus.subscribe(ch.channel_id, "agent-1")
    assert sub1.subscription_id == sub2.subscription_id


def test_subscribe_max_subscribers(bus):
    ch = bus.create_channel("limited", ChannelKind.PUBSUB, max_subscribers=2)
    bus.subscribe(ch.channel_id, "a1")
    bus.subscribe(ch.channel_id, "a2")
    assert bus.subscribe(ch.channel_id, "a3") is None


def test_unsubscribe(bus):
    ch = bus.create_channel("events", ChannelKind.PUBSUB)
    bus.subscribe(ch.channel_id, "agent-1")
    assert bus.unsubscribe(ch.channel_id, "agent-1")


def test_unsubscribe_not_subscribed(bus):
    ch = bus.create_channel("events", ChannelKind.PUBSUB)
    assert not bus.unsubscribe(ch.channel_id, "agent-1")


def test_publish_delivers_to_subscribers(bus):
    ch = bus.create_channel("events", ChannelKind.PUBSUB)
    bus.subscribe(ch.channel_id, "a1")
    bus.subscribe(ch.channel_id, "a2")

    msg = bus.publish(ch.channel_id, "a1", {"action": "deploy"})
    assert msg is not None

    inbox_a2 = bus.get_inbox("a2")
    assert len(inbox_a2) == 1
    assert inbox_a2[0].payload == {"action": "deploy"}

    inbox_a1 = bus.get_inbox("a1")
    assert len(inbox_a1) == 0


def test_publish_nonexistent_channel(bus):
    assert bus.publish("nonexistent", "a1", {}) is None


def test_publish_does_not_deliver_to_sender(bus):
    ch = bus.create_channel("events", ChannelKind.PUBSUB)
    bus.subscribe(ch.channel_id, "sender")
    bus.subscribe(ch.channel_id, "receiver")

    bus.publish(ch.channel_id, "sender", {"data": 1})
    assert len(bus.get_inbox("sender")) == 0
    assert len(bus.get_inbox("receiver")) == 1


def test_publish_does_not_deliver_to_unsubscribed(bus):
    ch = bus.create_channel("events", ChannelKind.PUBSUB)
    bus.subscribe(ch.channel_id, "a1")
    bus.subscribe(ch.channel_id, "a2")
    bus.unsubscribe(ch.channel_id, "a2")

    bus.publish(ch.channel_id, "a1", {"data": 1})
    assert len(bus.get_inbox("a2")) == 0


def test_request_reply(bus):
    ch = bus.create_channel("rpc", ChannelKind.REQUEST_REPLY)
    bus.subscribe(ch.channel_id, "server")
    bus.subscribe(ch.channel_id, "client")

    req = bus.request(ch.channel_id, "client", {"method": "get_status"})
    assert req is not None

    server_inbox = bus.get_inbox("server")
    assert len(server_inbox) == 1

    reply = bus.reply(req.message_id, "server", {"status": "ok"})
    assert reply is not None
    assert reply.reply_to == req.message_id

    client_inbox = bus.get_inbox("client")
    assert len(client_inbox) == 1
    assert client_inbox[0].payload == {"status": "ok"}


def test_request_on_non_rpc_channel(bus):
    ch = bus.create_channel("events", ChannelKind.PUBSUB)
    assert bus.request(ch.channel_id, "a1", {}) is None


def test_reply_to_nonexistent_message(bus):
    assert bus.reply("nonexistent", "a1", {}) is None


def test_get_replies(bus):
    ch = bus.create_channel("rpc", ChannelKind.REQUEST_REPLY)
    bus.subscribe(ch.channel_id, "server")
    bus.subscribe(ch.channel_id, "client")

    req = bus.request(ch.channel_id, "client", {"q": "hello"})
    bus.reply(req.message_id, "server", {"a": "world"})

    replies = bus.get_replies(req.message_id)
    assert len(replies) == 1
    assert replies[0].payload == {"a": "world"}


def test_inbox_priority_ordering(bus):
    ch = bus.create_channel("events", ChannelKind.PUBSUB)
    bus.subscribe(ch.channel_id, "receiver")

    bus.publish(ch.channel_id, "s1", {"p": "low"}, priority=MessagePriority.LOW)
    bus.publish(ch.channel_id, "s2", {"p": "urgent"}, priority=MessagePriority.URGENT)
    bus.publish(ch.channel_id, "s3", {"p": "normal"}, priority=MessagePriority.NORMAL)

    inbox = bus.get_inbox("receiver")
    assert inbox[0].payload["p"] == "urgent"
    assert inbox[1].payload["p"] == "normal"
    assert inbox[2].payload["p"] == "low"


def test_inbox_limit(bus):
    ch = bus.create_channel("events", ChannelKind.PUBSUB)
    bus.subscribe(ch.channel_id, "receiver")

    for i in range(10):
        bus.publish(ch.channel_id, f"s{i}", {"i": i})

    inbox = bus.get_inbox("receiver", limit=3)
    assert len(inbox) == 3


def test_acknowledge_message(bus):
    ch = bus.create_channel("events", ChannelKind.PUBSUB)
    bus.subscribe(ch.channel_id, "receiver")
    msg = bus.publish(ch.channel_id, "sender", {"data": 1})

    assert bus.acknowledge(msg.message_id, "receiver")


def test_acknowledge_nonexistent(bus):
    assert not bus.acknowledge("nonexistent", "receiver")


def test_direct_channel_delivers_to_one(bus):
    ch = bus.create_channel("direct", ChannelKind.DIRECT)
    bus.subscribe(ch.channel_id, "a1")
    bus.subscribe(ch.channel_id, "a2")
    bus.subscribe(ch.channel_id, "a3")

    bus.publish(ch.channel_id, "sender", {"msg": "hello"})
    total_delivered = sum(
        len(bus.get_inbox(f"a{i}")) for i in range(1, 4)
    )
    assert total_delivered == 1


def test_stats_empty(bus):
    stats = bus.get_stats()
    assert stats.total_channels == 0
    assert stats.total_messages == 0


def test_stats_with_data(bus):
    ch1 = bus.create_channel("events", ChannelKind.PUBSUB)
    ch2 = bus.create_channel("rpc", ChannelKind.REQUEST_REPLY)
    bus.subscribe(ch1.channel_id, "a1")
    bus.subscribe(ch1.channel_id, "a2")
    bus.subscribe(ch2.channel_id, "a3")

    bus.publish(ch1.channel_id, "a1", {"x": 1})
    bus.publish(ch1.channel_id, "a1", {"x": 2})

    stats = bus.get_stats()
    assert stats.total_channels == 2
    assert stats.total_messages == 2
    assert stats.total_subscriptions == 3
    assert stats.messages_delivered == 2
    assert stats.by_channel_kind["pubsub"] == 1
    assert stats.by_channel_kind["request_reply"] == 1


def test_correlation_id_propagated(bus):
    ch = bus.create_channel("events", ChannelKind.PUBSUB)
    bus.subscribe(ch.channel_id, "receiver")

    msg = bus.publish(ch.channel_id, "sender", {"x": 1}, correlation_id="corr-123")
    assert msg.correlation_id == "corr-123"

    inbox = bus.get_inbox("receiver")
    assert inbox[0].correlation_id == "corr-123"
