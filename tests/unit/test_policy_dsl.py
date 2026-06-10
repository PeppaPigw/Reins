"""Tests for declarative policy DSL engine."""

from __future__ import annotations

import pytest

from reins.policy_dsl import (
    Condition,
    ConditionOp,
    PolicyDSLEngine,
    PolicyEvaluation,
    PolicyRule,
    PolicyScope,
    PolicySet,
    RuleEffect,
)


@pytest.fixture
def engine() -> PolicyDSLEngine:
    return PolicyDSLEngine()


def test_add_rule(engine):
    rule = engine.add_rule(
        "block_prod_writes",
        conditions=[Condition(field="action", op=ConditionOp.EQUALS, value="write"),
                    Condition(field="target", op=ConditionOp.EQUALS, value="production")],
        effect=RuleEffect.DENY,
    )
    assert rule.name == "block_prod_writes"
    assert rule.effect == RuleEffect.DENY


def test_remove_rule(engine):
    rule = engine.add_rule("x", conditions=[], effect=RuleEffect.ALLOW)
    assert engine.remove_rule(rule.rule_id) is True
    assert engine.remove_rule("nonexistent") is False


def test_disable_enable_rule(engine):
    rule = engine.add_rule("x", conditions=[], effect=RuleEffect.ALLOW)
    assert engine.disable_rule(rule.rule_id) is True
    assert engine.get_rule(rule.rule_id).enabled is False
    assert engine.enable_rule(rule.rule_id) is True
    assert engine.get_rule(rule.rule_id).enabled is True


def test_evaluate_match(engine):
    engine.add_rule(
        "allow_reads",
        conditions=[Condition(field="action", op=ConditionOp.EQUALS, value="read")],
        effect=RuleEffect.ALLOW,
    )
    result = engine.evaluate({"action": "read", "agent": "a"})
    assert result.effect == RuleEffect.ALLOW
    assert result.matched is True


def test_evaluate_no_match_default_deny(engine):
    engine.add_rule(
        "allow_reads",
        conditions=[Condition(field="action", op=ConditionOp.EQUALS, value="read")],
        effect=RuleEffect.ALLOW,
    )
    result = engine.evaluate({"action": "write"})
    assert result.effect == RuleEffect.DENY
    assert result.matched is False


def test_priority_ordering(engine):
    engine.add_rule("low", conditions=[], effect=RuleEffect.DENY, priority=1)
    engine.add_rule("high", conditions=[], effect=RuleEffect.ALLOW, priority=10)
    result = engine.evaluate({"action": "anything"})
    assert result.effect == RuleEffect.ALLOW
    assert result.rule_name == "high"


def test_condition_not_equals(engine):
    engine.add_rule(
        "non_admin",
        conditions=[Condition(field="role", op=ConditionOp.NOT_EQUALS, value="admin")],
        effect=RuleEffect.DENY,
    )
    assert engine.evaluate({"role": "user"}).effect == RuleEffect.DENY
    assert engine.evaluate({"role": "admin"}).matched is False


def test_condition_in(engine):
    engine.add_rule(
        "trusted_agents",
        conditions=[Condition(field="agent", op=ConditionOp.IN,
                              value=["agent-1", "agent-2"])],
        effect=RuleEffect.ALLOW,
    )
    assert engine.evaluate({"agent": "agent-1"}).effect == RuleEffect.ALLOW
    assert engine.evaluate({"agent": "agent-3"}).matched is False


def test_condition_not_in(engine):
    engine.add_rule(
        "block_bad",
        conditions=[Condition(field="agent", op=ConditionOp.NOT_IN,
                              value=["trusted-1"])],
        effect=RuleEffect.DENY,
    )
    assert engine.evaluate({"agent": "unknown"}).effect == RuleEffect.DENY
    assert engine.evaluate({"agent": "trusted-1"}).matched is False


def test_condition_greater(engine):
    engine.add_rule(
        "high_cost",
        conditions=[Condition(field="cost", op=ConditionOp.GREATER, value=100)],
        effect=RuleEffect.ESCALATE,
    )
    assert engine.evaluate({"cost": 150}).effect == RuleEffect.ESCALATE
    assert engine.evaluate({"cost": 50}).matched is False


def test_condition_less(engine):
    engine.add_rule(
        "low_priority",
        conditions=[Condition(field="priority", op=ConditionOp.LESS, value=3)],
        effect=RuleEffect.THROTTLE,
    )
    assert engine.evaluate({"priority": 1}).effect == RuleEffect.THROTTLE


def test_condition_contains(engine):
    engine.add_rule(
        "sensitive_path",
        conditions=[Condition(field="path", op=ConditionOp.CONTAINS, value="/secrets/")],
        effect=RuleEffect.DENY,
    )
    assert engine.evaluate({"path": "/data/secrets/key.pem"}).effect == RuleEffect.DENY
    assert engine.evaluate({"path": "/data/public/readme"}).matched is False


def test_condition_matches_regex(engine):
    engine.add_rule(
        "sql_pattern",
        conditions=[Condition(field="query", op=ConditionOp.MATCHES,
                              value=r"DROP\s+TABLE")],
        effect=RuleEffect.DENY,
    )
    assert engine.evaluate({"query": "DROP TABLE users"}).effect == RuleEffect.DENY
    assert engine.evaluate({"query": "SELECT * FROM users"}).matched is False


def test_nested_field_resolution(engine):
    engine.add_rule(
        "nested",
        conditions=[Condition(field="agent.trust_level", op=ConditionOp.EQUALS,
                              value="high")],
        effect=RuleEffect.ALLOW,
    )
    result = engine.evaluate({"agent": {"trust_level": "high", "id": "a"}})
    assert result.effect == RuleEffect.ALLOW


def test_missing_field_no_match(engine):
    engine.add_rule(
        "check_role",
        conditions=[Condition(field="role", op=ConditionOp.EQUALS, value="admin")],
        effect=RuleEffect.ALLOW,
    )
    result = engine.evaluate({"action": "read"})
    assert result.matched is False


def test_multiple_conditions_all_must_match(engine):
    engine.add_rule(
        "strict",
        conditions=[
            Condition(field="action", op=ConditionOp.EQUALS, value="write"),
            Condition(field="role", op=ConditionOp.EQUALS, value="admin"),
        ],
        effect=RuleEffect.ALLOW,
    )
    assert engine.evaluate({"action": "write", "role": "admin"}).effect == RuleEffect.ALLOW
    assert engine.evaluate({"action": "write", "role": "user"}).matched is False


def test_policy_set(engine):
    r1 = engine.add_rule("allow_read",
                          conditions=[Condition(field="action", op=ConditionOp.EQUALS, value="read")],
                          effect=RuleEffect.ALLOW)
    r2 = engine.add_rule("deny_all", conditions=[], effect=RuleEffect.DENY)
    ps = engine.create_policy_set("read_only", [r1.rule_id],
                                   default_effect=RuleEffect.DENY)
    result = engine.evaluate({"action": "read"}, policy_set_id=ps.set_id)
    assert result.effect == RuleEffect.ALLOW
    result = engine.evaluate({"action": "write"}, policy_set_id=ps.set_id)
    assert result.effect == RuleEffect.DENY


def test_disabled_rule_skipped(engine):
    rule = engine.add_rule("x", conditions=[], effect=RuleEffect.ALLOW)
    engine.disable_rule(rule.rule_id)
    result = engine.evaluate({"action": "anything"})
    assert result.matched is False


def test_evaluate_all(engine):
    engine.add_rule("a", conditions=[Condition(field="x", op=ConditionOp.EQUALS, value=1)],
                    effect=RuleEffect.ALLOW)
    engine.add_rule("b", conditions=[Condition(field="x", op=ConditionOp.EQUALS, value=1)],
                    effect=RuleEffect.LOG)
    results = engine.evaluate_all({"x": 1})
    assert len(results) == 2
    assert all(r.matched for r in results)


def test_stats(engine):
    engine.add_rule("a", conditions=[], effect=RuleEffect.ALLOW, scope=PolicyScope.AGENT)
    engine.add_rule("b", conditions=[Condition(field="x", op=ConditionOp.EQUALS, value=1)],
                    effect=RuleEffect.DENY, scope=PolicyScope.GLOBAL)
    engine.evaluate({"x": 1})
    engine.evaluate({"x": 2})
    stats = engine.get_stats()
    assert stats.total_rules == 2
    assert stats.total_evaluations == 2
    assert stats.by_effect["allow"] == 1
    assert stats.by_scope["agent"] == 1
    assert stats.match_rate > 0


def test_all_effects(engine):
    for effect in RuleEffect:
        engine.add_rule(f"rule_{effect.value}", conditions=[], effect=effect, priority=0)
    assert len(engine.get_stats().by_effect) == len(RuleEffect)
