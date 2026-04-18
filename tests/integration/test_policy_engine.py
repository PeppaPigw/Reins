from __future__ import annotations

import pytest

from reins.kernel.intent.envelope import CommandProposal, IntentEnvelope
from reins.kernel.types import RiskTier
from reins.policy.audit import InMemoryPolicyAuditSink
from reins.policy.approval.ledger import EffectDescriptor
from reins.policy.capabilities import CAPABILITY_RISK_TIERS
from reins.policy.constraints import RuntimeConstraint
from reins.policy.engine import PolicyEngine
from reins.policy.rules import PolicyRule
from tests.integration.helpers import (
    assert_event_types_in_order,
    build_orchestrator_bundle,
    load_run_events,
)


@pytest.mark.asyncio
async def test_policy_engine_risk_tiers_and_decisions() -> None:
    engine = PolicyEngine()

    allow = await engine.evaluate(
        "fs.read",
        run_id="policy-eval",
        requested_by="model",
        effect_descriptor=EffectDescriptor(
            capability="fs.read",
            resource="README.md",
            intent_ref="intent-1",
            command_id="cmd-1",
        ),
    )
    ask = await engine.evaluate(
        "exec.shell.network",
        run_id="policy-eval",
        requested_by="model",
        effect_descriptor=EffectDescriptor(
            capability="exec.shell.network",
            resource="workspace",
            intent_ref="intent-2",
            command_id="cmd-2",
        ),
    )
    deny = await engine.evaluate(
        "deploy.prod",
        run_id="policy-eval",
        requested_by="model",
        effect_descriptor=EffectDescriptor(
            capability="deploy.prod",
            resource="prod",
            intent_ref="intent-3",
            command_id="cmd-3",
        ),
    )

    assert allow.decision == "allow"
    assert allow.risk_tier == RiskTier.T0
    assert allow.grant_id is not None
    assert ask.decision == "ask"
    assert ask.risk_tier == RiskTier.T2
    assert ask.grant_id is None
    assert deny.decision == "deny"
    assert deny.risk_tier == RiskTier.T4
    assert CAPABILITY_RISK_TIERS["git.push"] == RiskTier.T3


@pytest.mark.asyncio
async def test_policy_engine_keeps_default_behavior_without_rules_or_constraints() -> None:
    engine = PolicyEngine()

    decision = await engine.evaluate(
        "exec.shell.network",
        run_id="default-policy",
        requested_by="model",
        effect_descriptor=EffectDescriptor(
            capability="exec.shell.network",
            resource="workspace",
            intent_ref="intent-1",
            command_id="cmd-1",
        ),
    )

    assert decision.decision == "ask"
    assert decision.grant_id is None
    assert decision.matched_rule is None
    assert decision.triggered_constraints == ()


@pytest.mark.asyncio
async def test_policy_engine_rules_can_override_default_approval_path() -> None:
    engine = PolicyEngine(
        rules=[
            PolicyRule(
                name="auto-approve-network",
                condition='command.capability == "exec.shell.network"',
                action="auto_approve",
                reason="trusted network automation",
            )
        ]
    )

    decision = await engine.evaluate(
        "exec.shell.network",
        run_id="rule-policy",
        requested_by="model",
        effect_descriptor=EffectDescriptor(
            capability="exec.shell.network",
            resource="workspace",
            intent_ref="intent-2",
            command_id="cmd-2",
        ),
    )

    assert decision.decision == "allow"
    assert decision.grant_id is not None
    assert decision.reason == "trusted network automation"
    assert decision.matched_rule == "auto-approve-network"


@pytest.mark.asyncio
async def test_policy_engine_constraints_can_block_allowed_decisions() -> None:
    engine = PolicyEngine(
        rules=[
            PolicyRule(
                name="allow-network",
                condition='command.capability == "exec.shell.network"',
                action="allow",
                reason="rule allows network execution",
            )
        ],
        constraints=[
            RuntimeConstraint(
                name="network-rate-limit",
                kind="rate_limit",
                condition='command.capability == "exec.shell.network"',
                limit=1,
                window_seconds=60,
                action="require_approval",
                reason="network rate limit exceeded",
            )
        ],
    )
    effect = EffectDescriptor(
        capability="exec.shell.network",
        resource="workspace",
        intent_ref="intent-3",
        command_id="cmd-3",
    )

    first = await engine.evaluate(
        "exec.shell.network",
        run_id="constraint-policy",
        requested_by="model",
        effect_descriptor=effect,
    )
    second = await engine.evaluate(
        "exec.shell.network",
        run_id="constraint-policy",
        requested_by="model",
        effect_descriptor=effect,
    )

    assert first.decision == "allow"
    assert second.decision == "ask"
    assert second.triggered_constraints == ("network-rate-limit",)
    assert second.grant_id is None


@pytest.mark.asyncio
async def test_policy_engine_audit_sink_records_base_and_final_decisions() -> None:
    audit = InMemoryPolicyAuditSink()
    engine = PolicyEngine(
        rules=[
            PolicyRule(
                name="deny-shell",
                condition='command.capability == "exec.shell.sandboxed"',
                action="deny",
                reason="sandbox disabled in this run",
            )
        ],
        audit_sink=audit,
    )

    decision = await engine.evaluate(
        "exec.shell.sandboxed",
        run_id="audit-policy",
        requested_by="model",
        effect_descriptor=EffectDescriptor(
            capability="exec.shell.sandboxed",
            resource="workspace",
            intent_ref="intent-4",
            command_id="cmd-4",
        ),
    )

    assert decision.decision == "deny"
    assert len(audit.records) == 1
    record = audit.records[0]
    assert record.base_decision == "allow"
    assert record.decision == "deny"
    assert record.matched_rule == "deny-shell"
    assert record.resource == "workspace"


@pytest.mark.asyncio
async def test_policy_engine_rules_can_override_default_high_risk_deny() -> None:
    engine = PolicyEngine(
        rules=[
            PolicyRule(
                name="staging-prod-sandbox",
                condition='command.capability == "deploy.prod"',
                action="require_approval",
                reason="prod deploys require explicit human approval",
            )
        ]
    )

    decision = await engine.evaluate(
        "deploy.prod",
        run_id="high-risk-override",
        requested_by="model",
        effect_descriptor=EffectDescriptor(
            capability="deploy.prod",
            resource="prod",
            intent_ref="intent-5",
            command_id="cmd-5",
        ),
    )

    assert decision.decision == "ask"
    assert decision.grant_id is None
    assert decision.matched_rule == "staging-prod-sandbox"


@pytest.mark.asyncio
async def test_policy_engine_integration_audit_trail(tmp_path) -> None:
    bundle = build_orchestrator_bundle(tmp_path, run_id="policy-run")
    repo_root = bundle.repo_root
    sample = repo_root / "sample.txt"
    sample.write_text("policy sample\n", encoding="utf-8")

    orchestrator = bundle.orchestrator
    await orchestrator.intake(
        IntentEnvelope(run_id="policy-run", objective="Audit policy decisions")
    )
    await orchestrator.route()

    low_risk = await orchestrator.process_proposal(
        CommandProposal(
            run_id="policy-run",
            source="model",
            kind="fs.read",
            args={"root": str(repo_root), "path": "sample.txt"},
        )
    )
    assert low_risk["granted"] is True
    assert low_risk["executed"] is True

    gated_proposal = CommandProposal(
        run_id="policy-run",
        source="model",
        kind="exec.shell.network",
        args={"cmd": "echo approved", "cwd": str(repo_root)},
    )
    gated = await orchestrator.process_proposal(gated_proposal)
    assert gated["granted"] is False
    assert gated["needs_approval"] is True
    grant = await orchestrator.approve(gated["request_id"], granted_by="human")
    assert grant is not None
    allowed = await orchestrator.process_proposal(gated_proposal)
    assert allowed["granted"] is True
    assert allowed["executed"] is True

    denied = await orchestrator.process_proposal(
        CommandProposal(
            run_id="policy-run",
            source="model",
            kind="deploy.prod",
            args={"target": "prod"},
        )
    )
    assert denied["granted"] is False
    assert "risk tier exceeds local policy" in denied["reason"]

    events = await load_run_events(bundle.journal, "policy-run")
    assert_event_types_in_order(
        events,
        [
            "run.started",
            "path.routed",
            "policy.grant_issued",
            "command.executed",
            "approval.requested",
            "approval.resolved",
            "policy.grant_issued",
            "command.executed",
        ],
    )
    assert any(event.type == "approval.requested" for event in events)
    assert any(
        event.type == "policy.grant_issued" and event.payload["capability"] == "exec.shell.network"
        for event in events
    )
