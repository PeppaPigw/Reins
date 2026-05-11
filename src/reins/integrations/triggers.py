"""Trigger mechanism for spawning runs from external webhook events."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from reins.integrations.webhooks import WebhookEvent, WebhookSource


class TriggerAction(str, Enum):
    """Actions that can be triggered by webhook events."""

    spawn_run = "spawn_run"
    create_task = "create_task"
    notify = "notify"


@dataclass(frozen=True)
class TriggerCondition:
    """Condition that must be met for a trigger to fire."""

    source: WebhookSource
    event_type: str
    filter: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TriggerRule:
    """A rule that maps a webhook event condition to an action."""

    name: str
    condition: TriggerCondition
    action: TriggerAction
    action_config: dict[str, str] = field(default_factory=dict)
    enabled: bool = True


class TriggerEngine:
    """Evaluates webhook events against configured trigger rules."""

    def __init__(self, rules: list[TriggerRule] | None = None):
        self._rules: list[TriggerRule] = list(rules) if rules else []

    def add_rule(self, rule: TriggerRule) -> None:
        """Add a trigger rule to the engine."""
        self._rules.append(rule)

    def remove_rule(self, name: str) -> None:
        """Remove a trigger rule by name."""
        self._rules = [r for r in self._rules if r.name != name]

    def get_rules(self) -> list[TriggerRule]:
        """Return all configured rules."""
        return list(self._rules)

    def get_enabled_rules(self) -> list[TriggerRule]:
        """Return only enabled rules."""
        return [r for r in self._rules if r.enabled]

    def evaluate(self, event: WebhookEvent) -> list[TriggerRule]:
        """Evaluate an event against all enabled rules. Returns matching rules."""
        return [
            rule for rule in self._rules
            if rule.enabled and self._matches_condition(event, rule.condition)
        ]

    def _matches_condition(
        self, event: WebhookEvent, condition: TriggerCondition
    ) -> bool:
        """Check if an event matches a trigger condition."""
        if event.source != condition.source:
            return False
        if event.event_type != condition.event_type:
            return False
        # Check filter criteria against event payload
        for key, expected_value in condition.filter.items():
            actual = self._extract_filter_value(event.payload, key)
            if actual != expected_value:
                return False
        return True

    def _extract_filter_value(self, payload: dict[str, Any], key: str) -> str | None:
        """Extract a filter value from the payload using dot-notation keys."""
        parts = key.split(".")
        current: Any = payload
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return str(current) if current is not None else None
