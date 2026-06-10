from __future__ import annotations

import fnmatch
import time
from collections import defaultdict
from typing import Any

from reins.event_bus import BusEvent, EventBus
from reins.reactive_mesh.types import (
    MeshStats,
    Reaction,
    ReactionKind,
    ReactiveRule,
    TriggerCondition,
)


class ReactiveMesh:
    """Reactive safety mesh that monitors the event bus and triggers automated responses.

    Connects to an EventBus, watches for safety-relevant patterns, and fires
    reactions (block, throttle, quarantine, rollback, escalate) when conditions are met.
    """

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._rules: dict[str, ReactiveRule] = {}
        self._reactions: list[Reaction] = []
        self._quarantined: set[str] = set()
        self._event_windows: dict[str, list[float]] = defaultdict(list)
        self._last_fired: dict[str, float] = {}
        self._reaction_handlers: dict[ReactionKind, list] = defaultdict(list)

        self._bus.subscribe("*", "reactive-mesh", self._on_event)

    def add_rule(self, name: str, trigger: TriggerCondition, topic_pattern: str,
                 reaction: ReactionKind, threshold: float = 0.0,
                 window_seconds: float = 60.0, cooldown_seconds: float = 10.0) -> ReactiveRule:
        rule = ReactiveRule(
            name=name, trigger=trigger, topic_pattern=topic_pattern,
            reaction=reaction, threshold=threshold,
            window_seconds=window_seconds, cooldown_seconds=cooldown_seconds,
        )
        self._rules[rule.rule_id] = rule
        return rule

    def remove_rule(self, rule_id: str) -> bool:
        return self._rules.pop(rule_id, None) is not None

    def on_reaction(self, kind: ReactionKind, handler: Any) -> None:
        self._reaction_handlers[kind].append(handler)

    def is_quarantined(self, agent_id: str) -> bool:
        return agent_id in self._quarantined

    def release_quarantine(self, agent_id: str) -> bool:
        if agent_id in self._quarantined:
            self._quarantined.discard(agent_id)
            return True
        return False

    def get_reactions(self, agent_id: str | None = None,
                      kind: ReactionKind | None = None) -> list[Reaction]:
        results = self._reactions
        if agent_id:
            results = [r for r in results if r.agent_id == agent_id]
        if kind:
            results = [r for r in results if r.kind == kind]
        return results

    def get_stats(self) -> MeshStats:
        by_kind: dict[str, int] = defaultdict(int)
        by_trigger: dict[str, int] = defaultdict(int)
        for r in self._reactions:
            by_kind[r.kind.value] += 1
        for rule in self._rules.values():
            by_trigger[rule.trigger.value] += 1

        return MeshStats(
            total_rules=len(self._rules),
            total_reactions=len(self._reactions),
            by_reaction_kind=dict(by_kind),
            by_trigger=dict(by_trigger),
            agents_quarantined=len(self._quarantined),
        )

    def _on_event(self, event: BusEvent) -> None:
        now = time.monotonic()
        for rule in self._rules.values():
            if not rule.enabled:
                continue
            if not fnmatch.fnmatch(event.topic, rule.topic_pattern):
                continue
            if self._in_cooldown(rule.rule_id, now, rule.cooldown_seconds):
                continue
            if self._should_fire(rule, event, now):
                self._fire(rule, event, now)

    def _should_fire(self, rule: ReactiveRule, event: BusEvent, now: float) -> bool:
        if rule.trigger == TriggerCondition.EVENT_MATCH:
            return True

        if rule.trigger == TriggerCondition.THRESHOLD_BREACH:
            key = f"{rule.rule_id}:{event.topic}"
            self._event_windows[key].append(now)
            cutoff = now - rule.window_seconds
            self._event_windows[key] = [t for t in self._event_windows[key] if t > cutoff]
            return len(self._event_windows[key]) >= rule.threshold

        if rule.trigger == TriggerCondition.PATTERN_DETECTED:
            return event.payload.get("pattern_match", False)

        if rule.trigger == TriggerCondition.ANOMALY:
            return event.payload.get("anomaly_score", 0.0) > rule.threshold

        return False

    def _fire(self, rule: ReactiveRule, event: BusEvent, now: float) -> None:
        agent_id = event.payload.get("agent_id", event.source)
        reaction = Reaction(
            rule_id=rule.rule_id, rule_name=rule.name,
            kind=rule.reaction, trigger_event_id=event.event_id,
            agent_id=agent_id, payload=event.payload,
        )
        self._reactions.append(reaction)
        self._last_fired[rule.rule_id] = now

        if rule.reaction == ReactionKind.QUARANTINE:
            self._quarantined.add(agent_id)

        for handler in self._reaction_handlers.get(rule.reaction, []):
            handler(reaction)

    def _in_cooldown(self, rule_id: str, now: float, cooldown: float) -> bool:
        last = self._last_fired.get(rule_id)
        if last is None:
            return False
        return (now - last) < cooldown
