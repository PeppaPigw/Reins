from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from reins.policy_dsl.types import (
    Condition,
    ConditionOp,
    PolicyDSLStats,
    PolicyEvaluation,
    PolicyRule,
    PolicyScope,
    PolicySet,
    RuleEffect,
)


class PolicyDSLEngine:
    """Declarative policy engine with rule-based evaluation.

    Defines policies as human-readable rules with conditions and effects.
    Evaluates rules against context with priority ordering, first-match
    semantics, and configurable default effects. Supports policy sets
    for grouping related rules.
    """

    def __init__(self) -> None:
        self._rules: dict[str, PolicyRule] = {}
        self._sets: dict[str, PolicySet] = {}
        self._evaluations: list[PolicyEvaluation] = []

    def add_rule(self, name: str, conditions: list[Condition],
                 effect: RuleEffect = RuleEffect.DENY,
                 scope: PolicyScope = PolicyScope.GLOBAL,
                 priority: int = 0,
                 description: str = "") -> PolicyRule:
        rule = PolicyRule(
            name=name, conditions=conditions, effect=effect,
            scope=scope, priority=priority, description=description,
        )
        self._rules[rule.rule_id] = rule
        return rule

    def remove_rule(self, rule_id: str) -> bool:
        return self._rules.pop(rule_id, None) is not None

    def get_rule(self, rule_id: str) -> PolicyRule | None:
        return self._rules.get(rule_id)

    def disable_rule(self, rule_id: str) -> bool:
        rule = self._rules.get(rule_id)
        if not rule:
            return False
        self._rules[rule_id] = rule.model_copy(update={"enabled": False})
        return True

    def enable_rule(self, rule_id: str) -> bool:
        rule = self._rules.get(rule_id)
        if not rule:
            return False
        self._rules[rule_id] = rule.model_copy(update={"enabled": True})
        return True

    def create_policy_set(self, name: str, rule_ids: list[str],
                          default_effect: RuleEffect = RuleEffect.DENY) -> PolicySet:
        ps = PolicySet(name=name, rules=rule_ids, default_effect=default_effect)
        self._sets[ps.set_id] = ps
        return ps

    def evaluate(self, context: dict[str, Any],
                 policy_set_id: str | None = None) -> PolicyEvaluation:
        rules = self._get_applicable_rules(policy_set_id)
        rules.sort(key=lambda r: -r.priority)

        for rule in rules:
            if not rule.enabled:
                continue
            if self._matches(rule, context):
                evaluation = PolicyEvaluation(
                    rule_id=rule.rule_id,
                    rule_name=rule.name,
                    effect=rule.effect,
                    matched=True,
                    context=context,
                )
                self._evaluations.append(evaluation)
                return evaluation

        default = RuleEffect.DENY
        if policy_set_id:
            ps = self._sets.get(policy_set_id)
            if ps:
                default = ps.default_effect

        evaluation = PolicyEvaluation(
            rule_id="",
            rule_name="default",
            effect=default,
            matched=False,
            context=context,
        )
        self._evaluations.append(evaluation)
        return evaluation

    def evaluate_all(self, context: dict[str, Any]) -> list[PolicyEvaluation]:
        results = []
        rules = sorted(self._rules.values(), key=lambda r: -r.priority)
        for rule in rules:
            if not rule.enabled:
                continue
            matched = self._matches(rule, context)
            ev = PolicyEvaluation(
                rule_id=rule.rule_id,
                rule_name=rule.name,
                effect=rule.effect,
                matched=matched,
                context=context,
            )
            results.append(ev)
        self._evaluations.extend(results)
        return results

    def get_evaluations(self, rule_id: str | None = None) -> list[PolicyEvaluation]:
        if rule_id:
            return [e for e in self._evaluations if e.rule_id == rule_id]
        return list(self._evaluations)

    def get_stats(self) -> PolicyDSLStats:
        by_effect: dict[str, int] = defaultdict(int)
        by_scope: dict[str, int] = defaultdict(int)
        for rule in self._rules.values():
            by_effect[rule.effect.value] += 1
            by_scope[rule.scope.value] += 1

        matched = sum(1 for e in self._evaluations if e.matched)
        rate = matched / len(self._evaluations) if self._evaluations else 0.0

        return PolicyDSLStats(
            total_rules=len(self._rules),
            total_evaluations=len(self._evaluations),
            total_policy_sets=len(self._sets),
            by_effect=dict(by_effect),
            by_scope=dict(by_scope),
            match_rate=rate,
        )

    def _get_applicable_rules(self, policy_set_id: str | None) -> list[PolicyRule]:
        if policy_set_id:
            ps = self._sets.get(policy_set_id)
            if ps:
                return [self._rules[rid] for rid in ps.rules if rid in self._rules]
        return list(self._rules.values())

    def _matches(self, rule: PolicyRule, context: dict[str, Any]) -> bool:
        for condition in rule.conditions:
            if not self._eval_condition(condition, context):
                return False
        return True

    def _eval_condition(self, cond: Condition, context: dict[str, Any]) -> bool:
        value = self._resolve_field(cond.field, context)
        match cond.op:
            case ConditionOp.EQUALS:
                return value == cond.value
            case ConditionOp.NOT_EQUALS:
                return value != cond.value
            case ConditionOp.IN:
                return value in cond.value
            case ConditionOp.NOT_IN:
                return value not in cond.value
            case ConditionOp.GREATER:
                return value is not None and value > cond.value
            case ConditionOp.LESS:
                return value is not None and value < cond.value
            case ConditionOp.CONTAINS:
                return cond.value in value if value else False
            case ConditionOp.MATCHES:
                return bool(re.search(cond.value, str(value))) if value else False
        return False

    def _resolve_field(self, field: str, context: dict[str, Any]) -> Any:
        parts = field.split(".")
        current: Any = context
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
            if current is None:
                return None
        return current
