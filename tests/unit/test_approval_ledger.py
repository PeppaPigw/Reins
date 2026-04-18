from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from reins.approval import ApprovalLedger
from reins.approval.delegation import ApprovalDelegationLedger
from reins.approval.ledger import EffectDescriptor
from reins.policy.approval.ledger import ApprovalLedger as LegacyApprovalLedger


def _effect(
    *,
    capability: str = "git.push",
    resource: str = "origin/main",
) -> EffectDescriptor:
    return EffectDescriptor(
        capability=capability,
        resource=resource,
        intent_ref="intent-1",
        command_id="cmd-1",
    )


@pytest.mark.asyncio
async def test_request_persists_reason_and_required_approvers(tmp_path):
    ledger = ApprovalLedger(tmp_path / "approvals")

    request = await ledger.request(
        "run-1",
        _effect(),
        "model",
        reason="destructive operation",
        required_approvers=["human", "policy-engine"],
    )

    assert request.reason == "destructive operation"
    assert request.required_approvers == ("human", "policy-engine")
    assert request.status == "pending"
    assert request.status_history[0].status == "pending"

    reloaded = ApprovalLedger(tmp_path / "approvals")
    assert len(reloaded.pending) == 1
    assert reloaded.pending[0].required_approvers == ("human", "policy-engine")

    audit_entries = reloaded.audit(kind="request.created", request_id=request.request_id)
    assert len(audit_entries) == 1
    assert audit_entries[0].details["required_approvers"] == [
        "human",
        "policy-engine",
    ]


@pytest.mark.asyncio
async def test_approve_records_grant_and_audit(tmp_path):
    ledger = ApprovalLedger(tmp_path / "approvals")
    request = await ledger.request(
        "run-2",
        _effect(capability="exec.shell.network", resource="/tmp/workspace"),
        "model",
        reason="networked execution",
    )

    grant = await ledger.approve(request.request_id, granted_by="human")

    assert grant is not None
    assert grant.granted_by == "human"
    assert grant.reason == "networked execution"
    assert grant.delegation_id is None
    assert ledger.pending == []

    entries = ledger.audit(actor="human", kind="request.approved")
    assert len(entries) == 1
    assert entries[0].grant_id == grant.grant_id


@pytest.mark.asyncio
async def test_delegated_approval_uses_scope_and_resource_matching(tmp_path):
    ledger = ApprovalLedger(tmp_path / "approvals")
    request = await ledger.request(
        "run-3",
        _effect(),
        "model",
        required_approvers=["human"],
    )
    delegation = await ledger.delegate(
        from_actor="human",
        to_actor="senior-agent",
        scope=["git.push"],
        resource_scope=["origin/*"],
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        note="release window",
    )

    grant = await ledger.approve(request.request_id, granted_by="senior-agent")

    assert grant is not None
    assert grant.delegation_id == delegation.delegation_id
    assert grant.delegated_by == "human"
    assert ledger.audit(actor="senior-agent", kind="request.approved")[0].details[
        "delegated_by"
    ] == "human"


@pytest.mark.asyncio
async def test_delegated_approval_out_of_scope_raises_and_keeps_request_pending(tmp_path):
    ledger = ApprovalLedger(tmp_path / "approvals")
    request = await ledger.request("run-4", _effect(), "model")
    await ledger.delegate(
        from_actor="human",
        to_actor="limited-agent",
        scope=["git.commit"],
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    with pytest.raises(PermissionError):
        await ledger.approve(request.request_id, granted_by="limited-agent")

    assert len(ledger.pending) == 1
    assert ledger.pending[0].request_id == request.request_id


@pytest.mark.asyncio
async def test_revoke_delegation_blocks_future_approval(tmp_path):
    ledger = ApprovalLedger(tmp_path / "approvals")
    request = await ledger.request("run-5", _effect(), "model")
    delegation = await ledger.delegate(
        from_actor="human",
        to_actor="senior-agent",
        scope=["git.push"],
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    revoked = await ledger.revoke_delegation(
        delegation.delegation_id,
        revoked_by="human",
    )

    assert revoked is not None
    assert revoked.revoked_by == "human"

    with pytest.raises(PermissionError):
        await ledger.approve(request.request_id, granted_by="senior-agent")

    revoke_entries = ledger.audit(kind="delegation.revoked")
    assert len(revoke_entries) == 1
    assert revoke_entries[0].delegation_id == delegation.delegation_id


@pytest.mark.asyncio
async def test_delegation_store_filters_expired_records(tmp_path):
    store = ApprovalDelegationLedger(tmp_path / "approvals")
    await store.delegate(
        from_actor="human",
        to_actor="senior-agent",
        scope=["git.push"],
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
        issued_at=datetime.now(UTC) - timedelta(minutes=10),
    )

    assert store.active_for("senior-agent") == []
    assert store.find_active(
        actor="senior-agent",
        capability="git.push",
        resource="origin/main",
        required_from=("human",),
    ) is None


def test_legacy_shim_reexports_new_package():
    assert LegacyApprovalLedger is ApprovalLedger
