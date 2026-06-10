from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, Callable

from reins.collaboration.types import (
    Channel,
    ChannelKind,
    ChannelStats,
    Delivery,
    DeliveryStatus,
    Message,
    MessagePriority,
    Subscription,
    SubscriptionStatus,
)


class CollaborationBus:
    """Typed message channels between agents with pub/sub, request/reply, and broadcast.

    Provides structured multi-agent communication with delivery tracking,
    priority queuing, and subscription filtering.
    """

    def __init__(self) -> None:
        self._channels: dict[str, Channel] = {}
        self._subscriptions: dict[str, list[Subscription]] = defaultdict(list)
        self._messages: dict[str, Message] = {}
        self._deliveries: list[Delivery] = []
        self._inboxes: dict[str, list[Message]] = defaultdict(list)
        self._handlers: dict[str, Callable[[Message], Any]] = {}

    def create_channel(self, name: str, kind: ChannelKind,
                       description: str = "", max_subscribers: int = 0,
                       message_ttl_ms: float = 60000.0) -> Channel:
        channel = Channel(
            name=name,
            kind=kind,
            description=description,
            max_subscribers=max_subscribers,
            message_ttl_ms=message_ttl_ms,
        )
        self._channels[channel.channel_id] = channel
        return channel

    def get_channel(self, channel_id: str) -> Channel | None:
        return self._channels.get(channel_id)

    def subscribe(self, channel_id: str, subscriber_id: str,
                  filter_tags: tuple[str, ...] = ()) -> Subscription | None:
        channel = self._channels.get(channel_id)
        if not channel:
            return None

        if channel.max_subscribers > 0:
            active = [s for s in self._subscriptions[channel_id]
                      if s.status == SubscriptionStatus.ACTIVE]
            if len(active) >= channel.max_subscribers:
                return None

        existing = [s for s in self._subscriptions[channel_id]
                    if s.subscriber_id == subscriber_id and s.status == SubscriptionStatus.ACTIVE]
        if existing:
            return existing[0]

        sub = Subscription(
            channel_id=channel_id,
            subscriber_id=subscriber_id,
            filter_tags=filter_tags,
        )
        self._subscriptions[channel_id].append(sub)
        return sub

    def unsubscribe(self, channel_id: str, subscriber_id: str) -> bool:
        subs = self._subscriptions.get(channel_id, [])
        for i, sub in enumerate(subs):
            if sub.subscriber_id == subscriber_id and sub.status == SubscriptionStatus.ACTIVE:
                self._subscriptions[channel_id][i] = Subscription(
                    subscription_id=sub.subscription_id,
                    channel_id=sub.channel_id,
                    subscriber_id=sub.subscriber_id,
                    status=SubscriptionStatus.CANCELLED,
                    filter_tags=sub.filter_tags,
                    created_at=sub.created_at,
                )
                return True
        return False

    def publish(self, channel_id: str, sender_id: str,
                payload: dict[str, Any], priority: MessagePriority = MessagePriority.NORMAL,
                correlation_id: str | None = None) -> Message | None:
        channel = self._channels.get(channel_id)
        if not channel:
            return None

        message = Message(
            channel_id=channel_id,
            sender_id=sender_id,
            payload=payload,
            priority=priority,
            correlation_id=correlation_id,
            ttl_ms=channel.message_ttl_ms,
        )
        self._messages[message.message_id] = message

        subscribers = [s for s in self._subscriptions.get(channel_id, [])
                       if s.status == SubscriptionStatus.ACTIVE and s.subscriber_id != sender_id]

        if channel.kind == ChannelKind.DIRECT:
            subscribers = subscribers[:1]

        for sub in subscribers:
            self._deliver(message, sub.subscriber_id)

        if channel.kind == ChannelKind.BROADCAST:
            all_subscriber_ids = {s.subscriber_id for s in subscribers}
            for other_channel_id, other_subs in self._subscriptions.items():
                if other_channel_id == channel_id:
                    continue
                for s in other_subs:
                    if s.subscriber_id not in all_subscriber_ids and s.subscriber_id != sender_id:
                        if s.status == SubscriptionStatus.ACTIVE:
                            self._deliver(message, s.subscriber_id)
                            all_subscriber_ids.add(s.subscriber_id)

        return message

    def request(self, channel_id: str, sender_id: str,
                payload: dict[str, Any]) -> Message | None:
        channel = self._channels.get(channel_id)
        if not channel or channel.kind != ChannelKind.REQUEST_REPLY:
            return None

        message = Message(
            channel_id=channel_id,
            sender_id=sender_id,
            payload=payload,
            ttl_ms=channel.message_ttl_ms,
        )
        self._messages[message.message_id] = message

        subscribers = [s for s in self._subscriptions.get(channel_id, [])
                       if s.status == SubscriptionStatus.ACTIVE and s.subscriber_id != sender_id]
        for sub in subscribers:
            self._deliver(message, sub.subscriber_id)

        return message

    def reply(self, original_message_id: str, sender_id: str,
              payload: dict[str, Any]) -> Message | None:
        original = self._messages.get(original_message_id)
        if not original:
            return None

        reply_msg = Message(
            channel_id=original.channel_id,
            sender_id=sender_id,
            payload=payload,
            reply_to=original_message_id,
            correlation_id=original.correlation_id or original.message_id,
        )
        self._messages[reply_msg.message_id] = reply_msg
        self._deliver(reply_msg, original.sender_id)
        return reply_msg

    def get_inbox(self, subscriber_id: str, limit: int = 50) -> list[Message]:
        messages = self._inboxes.get(subscriber_id, [])
        priority_order = {
            MessagePriority.URGENT: 0,
            MessagePriority.HIGH: 1,
            MessagePriority.NORMAL: 2,
            MessagePriority.LOW: 3,
        }
        sorted_msgs = sorted(messages, key=lambda m: (priority_order.get(m.priority, 2), m.created_at))
        return sorted_msgs[:limit]

    def acknowledge(self, message_id: str, subscriber_id: str) -> bool:
        for i, delivery in enumerate(self._deliveries):
            if delivery.message_id == message_id and delivery.recipient_id == subscriber_id:
                if delivery.status == DeliveryStatus.DELIVERED:
                    self._deliveries[i] = Delivery(
                        delivery_id=delivery.delivery_id,
                        message_id=delivery.message_id,
                        recipient_id=delivery.recipient_id,
                        status=DeliveryStatus.ACKNOWLEDGED,
                        delivered_at=delivery.delivered_at,
                        acknowledged_at=datetime.now(UTC),
                    )
                    return True
        return False

    def get_replies(self, message_id: str) -> list[Message]:
        return [m for m in self._messages.values() if m.reply_to == message_id]

    def get_stats(self) -> ChannelStats:
        if not self._channels:
            return ChannelStats()

        total_subs = sum(
            len([s for s in subs if s.status == SubscriptionStatus.ACTIVE])
            for subs in self._subscriptions.values()
        )
        delivered = sum(1 for d in self._deliveries if d.status in (DeliveryStatus.DELIVERED, DeliveryStatus.ACKNOWLEDGED))
        failed = sum(1 for d in self._deliveries if d.status == DeliveryStatus.FAILED)

        by_kind: dict[str, int] = defaultdict(int)
        for ch in self._channels.values():
            by_kind[ch.kind.value] += 1

        return ChannelStats(
            total_channels=len(self._channels),
            total_messages=len(self._messages),
            total_subscriptions=total_subs,
            messages_delivered=delivered,
            messages_failed=failed,
            by_channel_kind=dict(by_kind),
        )

    def _deliver(self, message: Message, recipient_id: str) -> None:
        delivery = Delivery(
            message_id=message.message_id,
            recipient_id=recipient_id,
            status=DeliveryStatus.DELIVERED,
            delivered_at=datetime.now(UTC),
        )
        self._deliveries.append(delivery)
        self._inboxes[recipient_id].append(message)
