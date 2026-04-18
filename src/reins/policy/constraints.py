"""Runtime policy constraints.

Constraints are stateful guards that can narrow a policy decision after rules
have been evaluated. They are optional and intentionally conservative: a
constraint never broadens access, it only converts an ``allow`` into ``ask`` or
``deny``.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from reins.policy.rules import PolicyExpressionError, SafeConditionEvaluator, lookup_path


CONSTRAINT_ACTION_ALIASES: dict[str, str] = {
    "ask": "ask",
    "require_approval": "ask",
    "deny": "deny",
}


@dataclass(frozen=True)
class RuntimeConstraint:
    """Declarative runtime guard.

    Supported kinds:
    - ``rate_limit``: limit matching policy allows within a sliding window
    """

    name: str
    kind: str
    limit: int
    window_seconds: int = 60
    action: str = "ask"
    condition: str | None = None
    group_by: str = "command.capability"
    reason: str | None = None
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def normalized_action(self) -> str:
        try:
            return CONSTRAINT_ACTION_ALIASES[self.action]
        except KeyError as exc:
            raise PolicyExpressionError(f"unsupported constraint action: {self.action!r}") from exc

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "RuntimeConstraint":
        name = str(data["name"])
        kind = str(data.get("kind", "rate_limit"))
        if "limit" not in data:
            raise PolicyExpressionError(f"runtime constraint {name!r} is missing a limit")
        metadata = {
            key: value
            for key, value in data.items()
            if key
            not in {
                "name",
                "kind",
                "limit",
                "window_seconds",
                "action",
                "condition",
                "group_by",
                "reason",
                "description",
            }
        }
        return cls(
            name=name,
            kind=kind,
            limit=int(data["limit"]),
            window_seconds=int(data.get("window_seconds", 60)),
            action=str(data.get("action", "ask")),
            condition=str(data["condition"]) if data.get("condition") is not None else None,
            group_by=str(data.get("group_by", "command.capability")),
            reason=str(data["reason"]) if data.get("reason") is not None else None,
            description=(str(data["description"]) if data.get("description") is not None else None),
            metadata=metadata,
        )


@dataclass(frozen=True)
class ConstraintOutcome:
    """Result of a triggered runtime constraint."""

    constraint: RuntimeConstraint
    decision: str
    reason: str


class ConstraintRegistry:
    """Stateful registry of runtime constraints."""

    def __init__(
        self,
        constraints: Sequence[RuntimeConstraint] | None = None,
        evaluator: SafeConditionEvaluator | None = None,
    ) -> None:
        self._constraints = tuple(constraints or ())
        self._evaluator = evaluator or SafeConditionEvaluator()
        self._windows: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    @classmethod
    def from_data(
        cls,
        data: Sequence[RuntimeConstraint | Mapping[str, Any]] | None,
    ) -> "ConstraintRegistry":
        if not data:
            return cls()
        constraints: list[RuntimeConstraint] = []
        for item in data:
            if isinstance(item, RuntimeConstraint):
                constraints.append(item)
            else:
                constraints.append(RuntimeConstraint.from_mapping(item))
        return cls(constraints)

    def __bool__(self) -> bool:
        return bool(self._constraints)

    @property
    def constraints(self) -> tuple[RuntimeConstraint, ...]:
        return self._constraints

    def evaluate(
        self,
        context: Mapping[str, Any],
        current_decision: str,
    ) -> ConstraintOutcome | None:
        if current_decision != "allow":
            return None
        for constraint in self._constraints:
            if constraint.condition and not self._evaluator.evaluate(constraint.condition, context):
                continue
            outcome = self._apply(constraint, context)
            if outcome is not None:
                return outcome
        return None

    def _apply(
        self,
        constraint: RuntimeConstraint,
        context: Mapping[str, Any],
    ) -> ConstraintOutcome | None:
        if constraint.kind != "rate_limit":
            raise PolicyExpressionError(f"unsupported runtime constraint kind: {constraint.kind!r}")

        key_value = lookup_path(context, constraint.group_by)
        if key_value is None:
            key_value = "global"
        bucket = self._windows[(constraint.name, str(key_value))]
        now = time.monotonic()
        cutoff = now - constraint.window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= constraint.limit:
            decision = constraint.normalized_action()
            reason = constraint.reason or (
                f"constraint {constraint.name} exceeded for {constraint.group_by}={key_value}"
            )
            return ConstraintOutcome(
                constraint=constraint,
                decision=decision,
                reason=reason,
            )
        bucket.append(now)
        return None
