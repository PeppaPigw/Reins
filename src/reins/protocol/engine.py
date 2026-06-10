from __future__ import annotations

from collections import defaultdict

from reins.protocol.types import (
    CapabilityOffer,
    Channel,
    ChannelState,
    MessageKind,
    NegotiationRecord,
    NegotiationStatus,
    ProtocolMessage,
    ProtocolStats,
)


class ProtocolEngine:
    """Formal inter-agent communication protocol.

    Provides structured message passing, capability negotiation,
    channel lifecycle management, and protocol compliance verification.
    Agents must negotiate capabilities before exchanging task messages.
    """

    def __init__(self) -> None:
        self._messages: list[ProtocolMessage] = []
        self._channels: dict[str, Channel] = {}
        self._negotiations: dict[str, NegotiationRecord] = {}
        self._offers: dict[str, CapabilityOffer] = {}

    def register_capabilities(self, agent_id: str,
                              capabilities: list[str],
                              constraints: list[str] | None = None,
                              max_concurrency: int = 1) -> CapabilityOffer:
        offer = CapabilityOffer(
            agent_id=agent_id,
            capabilities=capabilities,
            constraints=constraints or [],
            max_concurrency=max_concurrency,
        )
        self._offers[agent_id] = offer
        return offer

    def get_capabilities(self, agent_id: str) -> CapabilityOffer | None:
        return self._offers.get(agent_id)

    def open_channel(self, agent_a: str, agent_b: str) -> Channel:
        channel = Channel(agent_a=agent_a, agent_b=agent_b)
        self._channels[channel.channel_id] = channel
        return channel

    def close_channel(self, channel_id: str) -> Channel | None:
        channel = self._channels.get(channel_id)
        if not channel:
            return None
        updated = channel.model_copy(update={"state": ChannelState.CLOSED})
        self._channels[channel_id] = updated
        return updated

    def get_channel(self, channel_id: str) -> Channel | None:
        return self._channels.get(channel_id)

    def negotiate(self, initiator: str, responder: str,
                  requested_capabilities: list[str]) -> NegotiationRecord:
        record = NegotiationRecord(
            initiator=initiator,
            responder=responder,
            offered_capabilities=requested_capabilities,
        )
        self._negotiations[record.negotiation_id] = record
        return record

    def accept_negotiation(self, negotiation_id: str,
                           accepted: list[str] | None = None) -> NegotiationRecord | None:
        record = self._negotiations.get(negotiation_id)
        if not record:
            return None

        responder_offer = self._offers.get(record.responder)
        if not responder_offer:
            updated = record.model_copy(update={
                "status": NegotiationStatus.REJECTED,
            })
            self._negotiations[negotiation_id] = updated
            return updated

        available = set(responder_offer.capabilities)
        requested = set(accepted or record.offered_capabilities)
        granted = list(available & requested)

        if not granted:
            updated = record.model_copy(update={
                "status": NegotiationStatus.REJECTED,
            })
        else:
            updated = record.model_copy(update={
                "status": NegotiationStatus.ACCEPTED,
                "accepted_capabilities": granted,
            })

        self._negotiations[negotiation_id] = updated
        return updated

    def reject_negotiation(self, negotiation_id: str) -> NegotiationRecord | None:
        record = self._negotiations.get(negotiation_id)
        if not record:
            return None
        updated = record.model_copy(update={"status": NegotiationStatus.REJECTED})
        self._negotiations[negotiation_id] = updated
        return updated

    def send(self, sender: str, receiver: str, kind: MessageKind,
             payload: dict | None = None,
             channel_id: str | None = None,
             correlation_id: str = "") -> ProtocolMessage:
        msg = ProtocolMessage(
            kind=kind, sender=sender, receiver=receiver,
            payload=payload or {}, correlation_id=correlation_id,
        )
        self._messages.append(msg)

        if channel_id and channel_id in self._channels:
            ch = self._channels[channel_id]
            self._channels[channel_id] = ch.model_copy(
                update={"messages_sent": ch.messages_sent + 1}
            )

        return msg

    def get_messages(self, sender: str | None = None,
                     receiver: str | None = None,
                     kind: MessageKind | None = None) -> list[ProtocolMessage]:
        msgs = self._messages
        if sender:
            msgs = [m for m in msgs if m.sender == sender]
        if receiver:
            msgs = [m for m in msgs if m.receiver == receiver]
        if kind:
            msgs = [m for m in msgs if m.kind == kind]
        return msgs

    def get_negotiation(self, negotiation_id: str) -> NegotiationRecord | None:
        return self._negotiations.get(negotiation_id)

    def get_stats(self) -> ProtocolStats:
        by_kind: dict[str, int] = defaultdict(int)
        for m in self._messages:
            by_kind[m.kind.value] += 1

        by_state: dict[str, int] = defaultdict(int)
        active = 0
        for ch in self._channels.values():
            by_state[ch.state.value] += 1
            if ch.state != ChannelState.CLOSED:
                active += 1

        successful = sum(
            1 for n in self._negotiations.values()
            if n.status == NegotiationStatus.ACCEPTED
        )

        return ProtocolStats(
            total_messages=len(self._messages),
            total_channels=len(self._channels),
            active_channels=active,
            total_negotiations=len(self._negotiations),
            successful_negotiations=successful,
            by_kind=dict(by_kind),
            by_channel_state=dict(by_state),
        )
