from __future__ import annotations

import json

import pytest

from reins.policy.audit import InMemoryPolicyAuditSink, JsonlPolicyAuditSink, PolicyAuditRecord
from reins.policy.constraints import ConstraintRegistry, RuntimeConstraint
from reins.policy.rules import (
    PolicyExpressionError,
    PolicyRule,
    PolicyRuleSet,
    SafeConditionEvaluator,
    lookup_path,
)


def test_safe_condition_evaluator_supports_comparisons_and_boolean_logic() -> None:
    evaluator = SafeConditionEvaluator()
    context = {
        "command": {"risk_tier": 2, "capability": "exec.shell.network"},
        "adapter": {"type": "exec"},
        "policy": {"matched_grant": False},
    }

    assert evaluator.evaluate('command.risk_tier >= MEDIUM and adapter.type == "exec"', context)
    assert evaluator.evaluate('command.capability in ["exec.shell.network"]', context)
    assert evaluator.evaluate("not policy.matched_grant", context)


def test_safe_condition_evaluator_rejects_unsupported_syntax() -> None:
    evaluator = SafeConditionEvaluator()

    with pytest.raises(PolicyExpressionError):
        evaluator.evaluate('__import__("os")', {"command": {"risk_tier": 0}})


def test_lookup_path_handles_nested_mappings_and_missing_values() -> None:
    source = {"command": {"resource": {"path": "README.md"}}}

    assert lookup_path(source, "command.resource.path") == "README.md"
    assert lookup_path(source, "command.resource.missing") is None


def test_policy_rule_set_uses_first_matching_rule_and_normalizes_actions() -> None:
    rules = PolicyRuleSet.from_data(
        [
            {
                "name": "high-risk-review",
                "condition": "command.risk_tier >= HIGH",
                "action": "require_approval",
                "reason": "explicit approval required",
            },
            {
                "name": "fallback",
                "action": "allow",
            },
        ]
    )

    match = rules.evaluate({"command": {"risk_tier": 3}})
    assert match is not None
    assert match.rule.name == "high-risk-review"
    assert match.decision == "ask"
    assert match.reason == "explicit approval required"


def test_policy_rule_from_mapping_keeps_extra_metadata() -> None:
    rule = PolicyRule.from_mapping(
        {
            "name": "local-writes",
            "action": "allow",
            "condition": 'command.capability == "fs.write.workspace"',
            "owner": "policy-team",
        }
    )

    assert rule.metadata == {"owner": "policy-team"}
    assert rule.normalized_action() == "allow"


def test_constraint_registry_applies_rate_limits() -> None:
    registry = ConstraintRegistry.from_data(
        [
            {
                "name": "limit-network",
                "kind": "rate_limit",
                "condition": 'command.capability == "exec.shell.network"',
                "limit": 1,
                "window_seconds": 60,
                "action": "deny",
            }
        ]
    )
    context = {
        "command": {"capability": "exec.shell.network"},
        "adapter": {"type": "exec"},
    }

    assert registry.evaluate(context, "allow") is None
    outcome = registry.evaluate(context, "allow")
    assert outcome is not None
    assert outcome.decision == "deny"
    assert outcome.constraint.name == "limit-network"


def test_constraint_registry_ignores_non_allow_decisions() -> None:
    registry = ConstraintRegistry(
        constraints=[RuntimeConstraint(name="noop", kind="rate_limit", limit=1)]
    )

    assert registry.evaluate({"command": {"capability": "fs.read"}}, "ask") is None


@pytest.mark.asyncio
async def test_audit_sinks_capture_structured_records(tmp_path) -> None:
    record = PolicyAuditRecord.create(
        run_id="run-1",
        capability="fs.read",
        requested_by="model",
        risk_tier=0,
        decision="allow",
        reason="low-risk capability",
        resource="README.md",
    )

    memory = InMemoryPolicyAuditSink()
    await memory.record(record)
    assert memory.records == [record]

    jsonl_path = tmp_path / "policy-audit.jsonl"
    sink = JsonlPolicyAuditSink(jsonl_path)
    await sink.record(record)

    lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[0])
    assert payload["capability"] == "fs.read"
    assert payload["decision"] == "allow"
