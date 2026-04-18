"""Declarative policy rules with safe condition evaluation.

The rule surface is intentionally small so YAML-shaped policy files can be
translated directly into these structures without introducing a full expression
language or external dependency.

Supported condition syntax:
- literals: strings, numbers, booleans, ``None``
- root names: ``command``, ``effect``, ``request``, ``adapter``, ``policy``
- dotted attribute access: ``command.risk_tier``
- boolean operators: ``and``, ``or``, ``not``
- comparisons: ``==``, ``!=``, ``<``, ``<=``, ``>``, ``>=``, ``in``, ``not in``

Pattern:
- rules are evaluated top-to-bottom
- the first matching rule wins
- malformed rules fail closed in the caller
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


DECISION_ALIASES: dict[str, str] = {
    "allow": "allow",
    "auto_approve": "allow",
    "ask": "ask",
    "require_approval": "ask",
    "deny": "deny",
    "route_remote": "route_remote",
}

CONDITION_CONSTANTS: dict[str, Any] = {
    "T0": 0,
    "T1": 1,
    "T2": 2,
    "T3": 3,
    "T4": 4,
    "READ_ONLY": 0,
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}


class PolicyExpressionError(ValueError):
    """Raised when a policy condition is invalid or unsafe."""


def lookup_path(source: Any, path: str) -> Any:
    """Resolve dotted lookup paths against nested mappings or objects."""

    current = source
    for segment in path.split("."):
        if isinstance(current, Mapping):
            current = current.get(segment)
        else:
            current = getattr(current, segment, None)
        if current is None:
            return None
    return current


class SafeConditionEvaluator:
    """Evaluates a constrained expression language without ``eval``."""

    def __init__(self) -> None:
        self._cache: dict[str, ast.expr] = {}

    def evaluate(self, expression: str, context: Mapping[str, Any]) -> bool:
        if not expression.strip():
            return True
        node = self._cache.get(expression)
        if node is None:
            parsed = ast.parse(expression, mode="eval")
            node = parsed.body
            self._cache[expression] = node
        result = self._evaluate_node(node, context)
        if not isinstance(result, bool):
            raise PolicyExpressionError(f"policy condition must return a boolean: {expression!r}")
        return result

    def _evaluate_node(self, node: ast.AST, context: Mapping[str, Any]) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in CONDITION_CONSTANTS:
                return CONDITION_CONSTANTS[node.id]
            if node.id in context:
                return context[node.id]
            raise PolicyExpressionError(f"unknown name in policy expression: {node.id}")
        if isinstance(node, ast.Attribute):
            base = self._evaluate_node(node.value, context)
            return lookup_path(base, node.attr)
        if isinstance(node, ast.List):
            return [self._evaluate_node(item, context) for item in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(self._evaluate_node(item, context) for item in node.elts)
        if isinstance(node, ast.Set):
            return {self._evaluate_node(item, context) for item in node.elts}
        if isinstance(node, ast.BoolOp):
            values = [self._evaluate_node(item, context) for item in node.values]
            if isinstance(node.op, ast.And):
                return all(values)
            if isinstance(node.op, ast.Or):
                return any(values)
            raise PolicyExpressionError("unsupported boolean operator")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not self._evaluate_node(node.operand, context)
        if isinstance(node, ast.Compare):
            left = self._evaluate_node(node.left, context)
            for operator, comparator_node in zip(node.ops, node.comparators, strict=True):
                right = self._evaluate_node(comparator_node, context)
                if isinstance(operator, ast.Eq):
                    matched = left == right
                elif isinstance(operator, ast.NotEq):
                    matched = left != right
                elif isinstance(operator, ast.Gt):
                    matched = left > right
                elif isinstance(operator, ast.GtE):
                    matched = left >= right
                elif isinstance(operator, ast.Lt):
                    matched = left < right
                elif isinstance(operator, ast.LtE):
                    matched = left <= right
                elif isinstance(operator, ast.In):
                    matched = left in right
                elif isinstance(operator, ast.NotIn):
                    matched = left not in right
                else:
                    raise PolicyExpressionError("unsupported comparison operator")
                if not matched:
                    return False
                left = right
            return True
        raise PolicyExpressionError(
            f"unsupported syntax in policy expression: {ast.dump(node, include_attributes=False)}"
        )


@dataclass(frozen=True)
class PolicyRule:
    """A declarative policy rule loaded from code or YAML-shaped data."""

    name: str
    action: str
    condition: str | None = None
    reason: str | None = None
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def normalized_action(self) -> str:
        try:
            return DECISION_ALIASES[self.action]
        except KeyError as exc:
            raise PolicyExpressionError(f"unsupported policy action: {self.action!r}") from exc

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "PolicyRule":
        name = str(data["name"])
        action_value = data.get("action", data.get("decision"))
        if action_value is None:
            raise PolicyExpressionError(f"policy rule {name!r} is missing an action")
        metadata = {
            key: value
            for key, value in data.items()
            if key not in {"name", "action", "decision", "condition", "reason", "description"}
        }
        return cls(
            name=name,
            action=str(action_value),
            condition=(str(data["condition"]) if data.get("condition") is not None else None),
            reason=str(data["reason"]) if data.get("reason") is not None else None,
            description=(str(data["description"]) if data.get("description") is not None else None),
            metadata=metadata,
        )


@dataclass(frozen=True)
class RuleMatch:
    """A concrete rule match and the normalized decision it produced."""

    rule: PolicyRule
    decision: str
    reason: str


class PolicyRuleSet:
    """Ordered collection of declarative rules."""

    def __init__(
        self,
        rules: Sequence[PolicyRule] | None = None,
        evaluator: SafeConditionEvaluator | None = None,
    ) -> None:
        self._rules = tuple(rules or ())
        self._evaluator = evaluator or SafeConditionEvaluator()

    @classmethod
    def from_data(
        cls,
        data: Sequence[PolicyRule | Mapping[str, Any]] | None,
    ) -> "PolicyRuleSet":
        if not data:
            return cls()
        rules: list[PolicyRule] = []
        for item in data:
            if isinstance(item, PolicyRule):
                rules.append(item)
            else:
                rules.append(PolicyRule.from_mapping(item))
        return cls(rules)

    def __bool__(self) -> bool:
        return bool(self._rules)

    @property
    def rules(self) -> tuple[PolicyRule, ...]:
        return self._rules

    def evaluate(self, context: Mapping[str, Any]) -> RuleMatch | None:
        for rule in self._rules:
            if rule.condition and not self._evaluator.evaluate(rule.condition, context):
                continue
            decision = rule.normalized_action()
            reason = rule.reason or f"matched policy rule: {rule.name}"
            return RuleMatch(rule=rule, decision=decision, reason=reason)
        return None
