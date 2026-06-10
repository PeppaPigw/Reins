from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from reins.negotiation.types import (
    Agreement,
    Negotiation,
    NegotiationStats,
    NegotiationStatus,
    Offer,
    OfferKind,
    ResolutionStrategy,
)


class NegotiationEngine:
    """Multi-agent negotiation for resource allocation with offers, counteroffers, and resolution.

    Manages negotiation lifecycles, tracks offers and counteroffers,
    resolves agreements using configurable strategies, and detects deadlocks.
    """

    def __init__(self, default_max_rounds: int = 5) -> None:
        self._default_max_rounds = default_max_rounds
        self._negotiations: dict[str, Negotiation] = {}
        self._agreements: list[Agreement] = []

    def initiate(self, initiator: str, responder: str, kind: OfferKind,
                 initial_value: float = 0.0, terms: dict | None = None,
                 strategy: ResolutionStrategy = ResolutionStrategy.FIRST_ACCEPT,
                 max_rounds: int | None = None) -> Negotiation:
        neg = Negotiation(
            kind=kind,
            initiator=initiator,
            responder=responder,
            status=NegotiationStatus.OPEN,
            strategy=strategy,
            max_rounds=max_rounds or self._default_max_rounds,
        )
        initial_offer = Offer(
            negotiation_id=neg.negotiation_id,
            from_agent=initiator,
            to_agent=responder,
            kind=kind,
            value=initial_value,
            terms=terms or {},
        )
        neg = Negotiation(
            negotiation_id=neg.negotiation_id,
            kind=neg.kind,
            initiator=neg.initiator,
            responder=neg.responder,
            status=neg.status,
            strategy=neg.strategy,
            offers=(initial_offer,),
            max_rounds=neg.max_rounds,
            current_round=1,
            metadata=neg.metadata,
            created_at=neg.created_at,
        )
        self._negotiations[neg.negotiation_id] = neg
        return neg

    def counter_offer(self, negotiation_id: str, from_agent: str,
                      value: float, terms: dict | None = None) -> Offer | None:
        neg = self._negotiations.get(negotiation_id)
        if not neg or neg.status not in (NegotiationStatus.OPEN, NegotiationStatus.COUNTER_OFFERED):
            return None

        if neg.current_round >= neg.max_rounds:
            self._update_status(negotiation_id, NegotiationStatus.DEADLOCKED)
            return None

        last_offer = neg.offers[-1] if neg.offers else None
        to_agent = neg.initiator if from_agent == neg.responder else neg.responder

        offer = Offer(
            negotiation_id=negotiation_id,
            from_agent=from_agent,
            to_agent=to_agent,
            kind=neg.kind,
            value=value,
            terms=terms or {},
            is_counter=True,
            parent_offer_id=last_offer.offer_id if last_offer else None,
        )

        updated = Negotiation(
            negotiation_id=neg.negotiation_id,
            kind=neg.kind,
            initiator=neg.initiator,
            responder=neg.responder,
            status=NegotiationStatus.COUNTER_OFFERED,
            strategy=neg.strategy,
            offers=neg.offers + (offer,),
            max_rounds=neg.max_rounds,
            current_round=neg.current_round + 1,
            metadata=neg.metadata,
            created_at=neg.created_at,
        )
        self._negotiations[negotiation_id] = updated
        return offer

    def accept(self, negotiation_id: str, accepting_agent: str) -> Agreement | None:
        neg = self._negotiations.get(negotiation_id)
        if not neg or neg.status not in (NegotiationStatus.OPEN, NegotiationStatus.COUNTER_OFFERED):
            return None

        last_offer = neg.offers[-1] if neg.offers else None
        if not last_offer:
            return None

        agreement = Agreement(
            negotiation_id=negotiation_id,
            parties=(neg.initiator, neg.responder),
            final_value=last_offer.value,
            terms=last_offer.terms,
        )
        self._agreements.append(agreement)
        self._update_status(negotiation_id, NegotiationStatus.ACCEPTED)
        return agreement

    def reject(self, negotiation_id: str) -> bool:
        neg = self._negotiations.get(negotiation_id)
        if not neg or neg.status not in (NegotiationStatus.OPEN, NegotiationStatus.COUNTER_OFFERED):
            return False
        self._update_status(negotiation_id, NegotiationStatus.REJECTED)
        return True

    def split_difference(self, negotiation_id: str) -> Agreement | None:
        neg = self._negotiations.get(negotiation_id)
        if not neg or len(neg.offers) < 2:
            return None

        last_two = neg.offers[-2:]
        split_value = (last_two[0].value + last_two[1].value) / 2.0

        merged_terms = {**last_two[0].terms, **last_two[1].terms}

        agreement = Agreement(
            negotiation_id=negotiation_id,
            parties=(neg.initiator, neg.responder),
            final_value=split_value,
            terms=merged_terms,
        )
        self._agreements.append(agreement)
        self._update_status(negotiation_id, NegotiationStatus.ACCEPTED)
        return agreement

    def get_negotiation(self, negotiation_id: str) -> Negotiation | None:
        return self._negotiations.get(negotiation_id)

    def get_agreements(self, agent_id: str | None = None) -> list[Agreement]:
        if agent_id:
            return [a for a in self._agreements if agent_id in a.parties]
        return list(self._agreements)

    def get_active_negotiations(self, agent_id: str | None = None) -> list[Negotiation]:
        active = [
            n for n in self._negotiations.values()
            if n.status in (NegotiationStatus.OPEN, NegotiationStatus.COUNTER_OFFERED)
        ]
        if agent_id:
            active = [n for n in active if agent_id in (n.initiator, n.responder)]
        return active

    def get_stats(self) -> NegotiationStats:
        total = len(self._negotiations)
        open_count = sum(
            1 for n in self._negotiations.values()
            if n.status in (NegotiationStatus.OPEN, NegotiationStatus.COUNTER_OFFERED)
        )
        accepted = sum(1 for n in self._negotiations.values() if n.status == NegotiationStatus.ACCEPTED)
        rejected = sum(1 for n in self._negotiations.values() if n.status == NegotiationStatus.REJECTED)
        deadlocked = sum(1 for n in self._negotiations.values() if n.status == NegotiationStatus.DEADLOCKED)

        total_offers = sum(len(n.offers) for n in self._negotiations.values())
        rounds = [n.current_round for n in self._negotiations.values() if n.current_round > 0]
        avg_rounds = sum(rounds) / len(rounds) if rounds else 0.0

        concluded = accepted + rejected + deadlocked
        agreement_rate = accepted / concluded if concluded else 0.0

        by_kind: dict[str, int] = defaultdict(int)
        for n in self._negotiations.values():
            by_kind[n.kind.value] += 1

        return NegotiationStats(
            total_negotiations=total,
            open_negotiations=open_count,
            accepted=accepted,
            rejected=rejected,
            deadlocked=deadlocked,
            total_offers=total_offers,
            avg_rounds=avg_rounds,
            agreement_rate=agreement_rate,
            by_kind=dict(by_kind),
        )

    def _update_status(self, negotiation_id: str, status: NegotiationStatus) -> None:
        neg = self._negotiations[negotiation_id]
        resolved_at = datetime.now(UTC) if status in (
            NegotiationStatus.ACCEPTED, NegotiationStatus.REJECTED, NegotiationStatus.DEADLOCKED
        ) else None
        self._negotiations[negotiation_id] = Negotiation(
            negotiation_id=neg.negotiation_id,
            kind=neg.kind,
            initiator=neg.initiator,
            responder=neg.responder,
            status=status,
            strategy=neg.strategy,
            offers=neg.offers,
            max_rounds=neg.max_rounds,
            current_round=neg.current_round,
            metadata=neg.metadata,
            created_at=neg.created_at,
            resolved_at=resolved_at,
        )
