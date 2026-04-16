"""Tests for grant expiration checking in PolicyEngine."""

import pytest
import time

from reins.kernel.types import GrantRef, RiskTier
from reins.policy.approval.ledger import EffectDescriptor
from reins.policy.engine import PolicyEngine


@pytest.mark.asyncio
async def test_expired_grant_not_matched():
    """Expired grants should not be matched by policy engine."""
    engine = PolicyEngine()

    # Create an expired grant (issued 1 hour ago with 60 second TTL)
    expired_grant = GrantRef(
        grant_id="grant-1",
        capability="fs.read",
        scope="workspace",
        issued_to="model",
        ttl_seconds=60,
        approval_hash=None,
        issued_at=time.time() - 3600,  # 1 hour ago
    )

    effect = EffectDescriptor(
        capability="fs.read",
        resource="workspace",
        intent_ref="intent-1",
        command_id="cmd-1",
    )

    decision = await engine.evaluate(
        capability="fs.read",
        run_id="test-run",
        requested_by="model",
        effect_descriptor=effect,
        active_grants=[expired_grant],
    )

    # Should not match expired grant, should issue new grant (T0 auto-grants)
    assert decision.decision == "allow"
    assert decision.grant_id is not None  # New grant issued


@pytest.mark.asyncio
async def test_valid_grant_matched():
    """Valid (non-expired) grants should be matched."""
    engine = PolicyEngine()

    # Create a valid grant (issued now with 600 second TTL)
    valid_grant = GrantRef(
        grant_id="grant-2",
        capability="fs.read",
        scope="workspace",
        issued_to="model",
        ttl_seconds=600,
        approval_hash=None,
        issued_at=time.time(),
    )

    effect = EffectDescriptor(
        capability="fs.read",
        resource="workspace",
        intent_ref="intent-1",
        command_id="cmd-1",
    )

    decision = await engine.evaluate(
        capability="fs.read",
        run_id="test-run",
        requested_by="model",
        effect_descriptor=effect,
        active_grants=[valid_grant],
    )

    # Should match the valid grant
    assert decision.decision == "allow"
    assert decision.grant_id is None  # No new grant needed
    assert decision.reason == "matched active grant"


@pytest.mark.asyncio
async def test_grant_expiring_soon_still_valid():
    """Grants that are about to expire but haven't yet should still be valid."""
    engine = PolicyEngine()

    # Create a grant expiring in 5 seconds
    expiring_grant = GrantRef(
        grant_id="grant-3",
        capability="fs.read",
        scope="workspace",
        issued_to="model",
        ttl_seconds=10,
        approval_hash=None,
        issued_at=time.time() - 5,  # Issued 5 seconds ago, expires in 5 seconds
    )

    effect = EffectDescriptor(
        capability="fs.read",
        resource="workspace",
        intent_ref="intent-1",
        command_id="cmd-1",
    )

    decision = await engine.evaluate(
        capability="fs.read",
        run_id="test-run",
        requested_by="model",
        effect_descriptor=effect,
        active_grants=[expiring_grant],
    )

    # Should still match
    assert decision.decision == "allow"
    assert decision.grant_id is None
    assert decision.reason == "matched active grant"


@pytest.mark.asyncio
async def test_multiple_grants_expired_and_valid():
    """When multiple grants exist, only valid ones should be matched."""
    engine = PolicyEngine()

    expired_grant = GrantRef(
        grant_id="grant-expired",
        capability="fs.read",
        scope="workspace",
        issued_to="model",
        ttl_seconds=60,
        approval_hash=None,
        issued_at=time.time() - 3600,
    )

    valid_grant = GrantRef(
        grant_id="grant-valid",
        capability="fs.read",
        scope="workspace",
        issued_to="model",
        ttl_seconds=600,
        approval_hash=None,
        issued_at=time.time(),
    )

    effect = EffectDescriptor(
        capability="fs.read",
        resource="workspace",
        intent_ref="intent-1",
        command_id="cmd-1",
    )

    decision = await engine.evaluate(
        capability="fs.read",
        run_id="test-run",
        requested_by="model",
        effect_descriptor=effect,
        active_grants=[expired_grant, valid_grant],
    )

    # Should match the valid grant, not the expired one
    assert decision.decision == "allow"
    assert decision.grant_id is None
    assert decision.reason == "matched active grant"


@pytest.mark.asyncio
async def test_high_risk_capability_with_expired_grant():
    """High-risk capabilities with expired grants should require approval."""
    engine = PolicyEngine()

    expired_grant = GrantRef(
        grant_id="grant-expired",
        capability="exec.shell.network",
        scope="workspace",
        issued_to="model",
        ttl_seconds=60,
        approval_hash=None,
        issued_at=time.time() - 3600,
    )

    effect = EffectDescriptor(
        capability="exec.shell.network",
        resource="workspace",
        intent_ref="intent-1",
        command_id="cmd-1",
    )

    decision = await engine.evaluate(
        capability="exec.shell.network",
        run_id="test-run",
        requested_by="model",
        effect_descriptor=effect,
        active_grants=[expired_grant],
    )

    # T2 capability without valid grant should ask for approval
    assert decision.decision == "ask"
    assert decision.risk_tier == RiskTier.T2
