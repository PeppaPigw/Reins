"""Tests for zero-trust agent identity with capability attestation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from reins.identity import (
    AgentIdentity,
    AuthDecision,
    AuthRequest,
    CapabilityAttestation,
    Credential,
    CredentialKind,
    IdentityProvider,
    IdentityStats,
    TrustLevel,
)


@pytest.fixture
def provider() -> IdentityProvider:
    return IdentityProvider()


def test_register_identity(provider):
    identity = provider.register_identity("agent-1", display_name="Worker")
    assert identity.agent_id == "agent-1"
    assert identity.trust_level == TrustLevel.UNTRUSTED
    assert identity.fingerprint != ""


def test_get_identity(provider):
    provider.register_identity("agent-1")
    assert provider.get_identity("agent-1") is not None
    assert provider.get_identity("nonexistent") is None


def test_verify_identity(provider):
    provider.register_identity("agent-1")
    verified = provider.verify_identity("agent-1")
    assert verified.trust_level == TrustLevel.VERIFIED


def test_verify_already_verified(provider):
    provider.register_identity("agent-1")
    provider.verify_identity("agent-1")
    result = provider.verify_identity("agent-1")
    assert result.trust_level == TrustLevel.VERIFIED


def test_verify_not_found(provider):
    assert provider.verify_identity("nonexistent") is None


def test_elevate_trust(provider):
    provider.register_identity("agent-1")
    elevated = provider.elevate_trust("agent-1", TrustLevel.PRIVILEGED)
    assert elevated.trust_level == TrustLevel.PRIVILEGED


def test_elevate_trust_no_downgrade(provider):
    provider.register_identity("agent-1")
    provider.elevate_trust("agent-1", TrustLevel.PRIVILEGED)
    result = provider.elevate_trust("agent-1", TrustLevel.VERIFIED)
    assert result.trust_level == TrustLevel.PRIVILEGED


def test_elevate_not_found(provider):
    assert provider.elevate_trust("nonexistent", TrustLevel.VERIFIED) is None


def test_revoke_trust(provider):
    provider.register_identity("agent-1")
    provider.elevate_trust("agent-1", TrustLevel.PRIVILEGED)
    revoked = provider.revoke_trust("agent-1")
    assert revoked.trust_level == TrustLevel.UNTRUSTED


def test_revoke_trust_not_found(provider):
    assert provider.revoke_trust("nonexistent") is None


def test_issue_credential(provider):
    provider.register_identity("agent-1")
    cred = provider.issue_credential("agent-1", CredentialKind.API_KEY, "secret-key-123")
    assert cred.agent_id == "agent-1"
    assert cred.kind == CredentialKind.API_KEY
    assert cred.value_hash != ""
    assert cred.value_hash != "secret-key-123"


def test_verify_credential_valid(provider):
    provider.register_identity("agent-1")
    provider.issue_credential("agent-1", CredentialKind.TOKEN, "my-token")
    assert provider.verify_credential("agent-1", CredentialKind.TOKEN, "my-token") is True


def test_verify_credential_wrong_value(provider):
    provider.register_identity("agent-1")
    provider.issue_credential("agent-1", CredentialKind.TOKEN, "my-token")
    assert provider.verify_credential("agent-1", CredentialKind.TOKEN, "wrong") is False


def test_verify_credential_expired(provider):
    provider.register_identity("agent-1")
    past = datetime.now(UTC) - timedelta(hours=1)
    provider.issue_credential("agent-1", CredentialKind.TOKEN, "tok", expires_at=past)
    assert provider.verify_credential("agent-1", CredentialKind.TOKEN, "tok") is False


def test_revoke_credential(provider):
    provider.register_identity("agent-1")
    cred = provider.issue_credential("agent-1", CredentialKind.TOKEN, "tok")
    assert provider.revoke_credential(cred.credential_id) is True
    assert provider.verify_credential("agent-1", CredentialKind.TOKEN, "tok") is False


def test_revoke_credential_not_found(provider):
    assert provider.revoke_credential("nonexistent") is False


def test_attest_capability(provider):
    provider.register_identity("agent-1")
    att = provider.attest_capability("agent-1", "code_review", attested_by="admin")
    assert att.capability == "code_review"
    assert att.checksum != ""
    identity = provider.get_identity("agent-1")
    assert "code_review" in identity.capabilities
    assert identity.trust_level == TrustLevel.ATTESTED


def test_has_capability(provider):
    provider.register_identity("agent-1")
    provider.attest_capability("agent-1", "deploy")
    assert provider.has_capability("agent-1", "deploy") is True
    assert provider.has_capability("agent-1", "admin") is False


def test_has_capability_expired(provider):
    provider.register_identity("agent-1")
    past = datetime.now(UTC) - timedelta(hours=1)
    provider.attest_capability("agent-1", "temp_access", valid_until=past)
    assert provider.has_capability("agent-1", "temp_access") is False


def test_authorize_allow(provider):
    provider.register_identity("agent-1")
    provider.verify_identity("agent-1")
    provider.set_access_policy("database", TrustLevel.VERIFIED)
    result = provider.authorize("agent-1", "database")
    assert result.decision == AuthDecision.ALLOW


def test_authorize_deny_unknown(provider):
    result = provider.authorize("unknown", "database")
    assert result.decision == AuthDecision.DENY


def test_authorize_deny_insufficient_trust(provider):
    provider.register_identity("agent-1")
    provider.set_access_policy("admin_panel", TrustLevel.SYSTEM)
    result = provider.authorize("agent-1", "admin_panel")
    assert result.decision == AuthDecision.DENY


def test_authorize_challenge(provider):
    provider.register_identity("agent-1")
    provider.verify_identity("agent-1")
    provider.set_access_policy("sensitive", TrustLevel.ATTESTED)
    result = provider.authorize("agent-1", "sensitive")
    assert result.decision == AuthDecision.CHALLENGE


def test_get_auth_log(provider):
    provider.register_identity("a")
    provider.register_identity("b")
    provider.authorize("a", "res1")
    provider.authorize("b", "res2")
    assert len(provider.get_auth_log()) == 2
    assert len(provider.get_auth_log(agent_id="a")) == 1


def test_get_auth_log_by_decision(provider):
    provider.register_identity("a")
    provider.verify_identity("a")
    provider.set_access_policy("open", TrustLevel.VERIFIED)
    provider.set_access_policy("closed", TrustLevel.SYSTEM)
    provider.authorize("a", "open")
    provider.authorize("a", "closed")
    denied = provider.get_auth_log(decision=AuthDecision.DENY)
    assert len(denied) == 1


def test_stats_empty(provider):
    stats = provider.get_stats()
    assert stats.total_identities == 0


def test_stats_populated(provider):
    provider.register_identity("a")
    provider.register_identity("b")
    provider.verify_identity("a")
    provider.issue_credential("a", CredentialKind.TOKEN, "tok")
    provider.attest_capability("a", "deploy")
    provider.authorize("a", "resource")
    provider.authorize("unknown", "resource")
    stats = provider.get_stats()
    assert stats.total_identities == 2
    assert stats.total_credentials == 1
    assert stats.total_attestations == 1
    assert stats.auth_requests == 2
    assert stats.denied_requests == 1
    assert "attested" in stats.by_trust_level
