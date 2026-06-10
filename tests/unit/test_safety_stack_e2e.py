"""Integration test: full safety stack end-to-end.

Demonstrates the complete Reins safety pipeline:
identity + protocol + composability + invariants + safety kernel + audit chain
"""

from __future__ import annotations

import pytest

from reins.audit_chain import AuditAction, AuditChain, AuditSeverity, IntegrityStatus
from reins.composability import ComposabilityEngine, CompositionKind, SafetyRelation
from reins.identity import AuthDecision, IdentityProvider, TrustLevel
from reins.invariants import CheckResult, InvariantChecker, InvariantKind
from reins.protocol import MessageKind, NegotiationStatus, ProtocolEngine
from reins.safety_kernel import GateStage, GateVerdict, SafetyKernel


@pytest.fixture
def stack():
    identity = IdentityProvider()
    protocol = ProtocolEngine()
    composability = ComposabilityEngine()
    invariants = InvariantChecker()
    kernel = SafetyKernel()
    audit = AuditChain()

    agent_a = identity.register_identity("reviewer", display_name="Code Reviewer")
    identity.issue_credential(agent_a.agent_id, "api_key", "sha256:abc")
    identity.attest_capability(agent_a.agent_id, "code_review")
    identity.elevate_trust(agent_a.agent_id, TrustLevel.VERIFIED)

    agent_b = identity.register_identity("writer", display_name="Code Writer")
    identity.issue_credential(agent_b.agent_id, "api_key", "sha256:def")
    identity.attest_capability(agent_b.agent_id, "code_generation")
    identity.elevate_trust(agent_b.agent_id, TrustLevel.VERIFIED)

    protocol.register_capabilities("reviewer", ["code_review", "feedback"])
    protocol.register_capabilities("writer", ["code_generation", "testing"])

    composability.register_contract(
        "reviewer", requires={"source_code"}, provides={"review_feedback"},
        modifies=set(), invariants=["no_code_modification"],
    )
    composability.register_contract(
        "writer", requires={"review_feedback"}, provides={"source_code"},
        modifies={"codebase"}, invariants=["test_coverage"],
    )

    no_unauth = invariants.define_invariant(
        "authenticated", InvariantKind.SAFETY,
        checker=lambda s: s.get("authenticated", False),
    )

    def identity_gate(ctx):
        agent_id = ctx.get("agent_id", "")
        ident = identity.get_identity(agent_id)
        if ident and ident.trust_level != TrustLevel.UNTRUSTED:
            return GateVerdict.ALLOW
        return GateVerdict.DENY

    def invariant_gate(ctx):
        result = invariants.check(no_unauth.spec_id, ctx)
        if result.result == CheckResult.SATISFIED:
            return GateVerdict.ALLOW
        return GateVerdict.DENY

    kernel.register_gate(GateStage.IDENTITY, identity_gate)
    kernel.register_gate(GateStage.INVARIANTS, invariant_gate)

    return {
        "identity": identity,
        "protocol": protocol,
        "composability": composability,
        "invariants": invariants,
        "kernel": kernel,
        "audit": audit,
        "no_unauth": no_unauth,
    }


def test_authorized_agent_passes(stack):
    result = stack["kernel"].evaluate({
        "agent_id": "reviewer", "authenticated": True,
    })
    assert result.final_verdict == GateVerdict.ALLOW


def test_unknown_agent_blocked(stack):
    result = stack["kernel"].evaluate({
        "agent_id": "hacker", "authenticated": False,
    })
    assert result.final_verdict == GateVerdict.DENY


def test_protocol_negotiation(stack):
    neg = stack["protocol"].negotiate("writer", "reviewer",
                                       requested_capabilities=["code_review"])
    accepted = stack["protocol"].accept_negotiation(neg.negotiation_id)
    assert accepted.status == NegotiationStatus.ACCEPTED


def test_composability_safe(stack):
    comp = stack["composability"].compose(
        "review_pipeline", ["writer", "reviewer"],
        kind=CompositionKind.SEQUENTIAL,
    )
    proof = stack["composability"].verify_composition(comp.composition_id)
    assert proof.relation == SafetyRelation.PRESERVES


def test_audit_chain_integrity(stack):
    audit = stack["audit"]
    audit.record(AuditAction.AGENT_STARTED, agent_id="reviewer")
    audit.record(AuditAction.POLICY_EVALUATED, agent_id="reviewer")
    audit.record(AuditAction.TOOL_INVOKED, agent_id="reviewer")
    audit.record(AuditAction.AGENT_COMPLETED, agent_id="reviewer")
    assert audit.verify().status == IntegrityStatus.VALID


def test_full_pipeline_batch(stack):
    results = stack["kernel"].evaluate_batch([
        {"agent_id": "reviewer", "authenticated": True},
        {"agent_id": "writer", "authenticated": True},
        {"agent_id": "unknown", "authenticated": False},
    ])
    assert results[0].final_verdict == GateVerdict.ALLOW
    assert results[1].final_verdict == GateVerdict.ALLOW
    assert results[2].final_verdict == GateVerdict.DENY
