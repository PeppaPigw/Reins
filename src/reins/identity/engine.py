from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import UTC, datetime

from reins.identity.types import (
    AgentIdentity,
    AuthDecision,
    AuthRequest,
    CapabilityAttestation,
    Credential,
    CredentialKind,
    IdentityStats,
    TrustLevel,
)

_TRUST_HIERARCHY = [
    TrustLevel.UNTRUSTED,
    TrustLevel.VERIFIED,
    TrustLevel.ATTESTED,
    TrustLevel.PRIVILEGED,
    TrustLevel.SYSTEM,
]


class IdentityProvider:
    """Zero-trust agent identity with cryptographic verification and capability attestation.

    Provides agent identity lifecycle, credential management, capability attestation,
    and authorization decisions based on trust levels and verified capabilities.
    No agent is trusted by default — trust must be earned through verification.
    """

    def __init__(self) -> None:
        self._identities: dict[str, AgentIdentity] = {}
        self._credentials: dict[str, list[Credential]] = defaultdict(list)
        self._attestations: dict[str, list[CapabilityAttestation]] = defaultdict(list)
        self._auth_log: list[AuthRequest] = []
        self._access_policies: dict[str, TrustLevel] = {}

    def register_identity(self, agent_id: str, display_name: str = "",
                          capabilities: list[str] | None = None,
                          issuer: str = "") -> AgentIdentity:
        fingerprint = self._compute_fingerprint(agent_id, issuer)
        identity = AgentIdentity(
            agent_id=agent_id,
            display_name=display_name or agent_id,
            fingerprint=fingerprint,
            capabilities=tuple(capabilities or []),
            issuer=issuer,
        )
        self._identities[agent_id] = identity
        return identity

    def get_identity(self, agent_id: str) -> AgentIdentity | None:
        return self._identities.get(agent_id)

    def verify_identity(self, agent_id: str) -> AgentIdentity | None:
        identity = self._identities.get(agent_id)
        if not identity:
            return None
        if identity.trust_level == TrustLevel.UNTRUSTED:
            updated = identity.model_copy(update={"trust_level": TrustLevel.VERIFIED})
            self._identities[agent_id] = updated
            return updated
        return identity

    def elevate_trust(self, agent_id: str, level: TrustLevel) -> AgentIdentity | None:
        identity = self._identities.get(agent_id)
        if not identity:
            return None
        current_idx = _TRUST_HIERARCHY.index(identity.trust_level)
        target_idx = _TRUST_HIERARCHY.index(level)
        if target_idx <= current_idx:
            return identity
        updated = identity.model_copy(update={"trust_level": level})
        self._identities[agent_id] = updated
        return updated

    def revoke_trust(self, agent_id: str) -> AgentIdentity | None:
        identity = self._identities.get(agent_id)
        if not identity:
            return None
        updated = identity.model_copy(update={"trust_level": TrustLevel.UNTRUSTED})
        self._identities[agent_id] = updated
        return updated

    def issue_credential(self, agent_id: str, kind: CredentialKind,
                         value: str, expires_at: datetime | None = None) -> Credential:
        value_hash = hashlib.sha256(value.encode()).hexdigest()
        credential = Credential(
            agent_id=agent_id,
            kind=kind,
            value_hash=value_hash,
            expires_at=expires_at,
        )
        self._credentials[agent_id].append(credential)
        return credential

    def verify_credential(self, agent_id: str, kind: CredentialKind,
                          value: str) -> bool:
        value_hash = hashlib.sha256(value.encode()).hexdigest()
        now = datetime.now(UTC)
        for cred in self._credentials.get(agent_id, []):
            if cred.kind != kind or cred.revoked:
                continue
            if cred.expires_at and now > cred.expires_at:
                continue
            if cred.value_hash == value_hash:
                return True
        return False

    def revoke_credential(self, credential_id: str) -> bool:
        for agent_creds in self._credentials.values():
            for i, cred in enumerate(agent_creds):
                if cred.credential_id == credential_id:
                    agent_creds[i] = cred.model_copy(update={"revoked": True})
                    return True
        return False

    def attest_capability(self, agent_id: str, capability: str,
                          attested_by: str = "",
                          evidence: str = "",
                          valid_until: datetime | None = None) -> CapabilityAttestation:
        checksum = hashlib.sha256(
            f"{agent_id}:{capability}:{attested_by}".encode()
        ).hexdigest()[:16]
        attestation = CapabilityAttestation(
            agent_id=agent_id,
            capability=capability,
            attested_by=attested_by,
            evidence=evidence,
            valid_until=valid_until,
            checksum=checksum,
        )
        self._attestations[agent_id].append(attestation)

        identity = self._identities.get(agent_id)
        if identity and capability not in identity.capabilities:
            new_caps = identity.capabilities + (capability,)
            self._identities[agent_id] = identity.model_copy(
                update={"capabilities": new_caps}
            )
            if identity.trust_level.value in ("untrusted", "verified"):
                self._identities[agent_id] = self._identities[agent_id].model_copy(
                    update={"trust_level": TrustLevel.ATTESTED}
                )

        return attestation

    def has_capability(self, agent_id: str, capability: str) -> bool:
        now = datetime.now(UTC)
        for att in self._attestations.get(agent_id, []):
            if att.capability != capability:
                continue
            if att.valid_until and now > att.valid_until:
                continue
            return True
        return False

    def set_access_policy(self, resource: str, min_trust: TrustLevel) -> None:
        self._access_policies[resource] = min_trust

    def authorize(self, agent_id: str, resource: str,
                  action: str = "access") -> AuthRequest:
        identity = self._identities.get(agent_id)

        if not identity:
            request = AuthRequest(
                requester_id=agent_id,
                target_resource=resource,
                action=action,
                decision=AuthDecision.DENY,
                reason="Unknown identity",
            )
            self._auth_log.append(request)
            return request

        required_trust = self._access_policies.get(resource, TrustLevel.VERIFIED)
        agent_idx = _TRUST_HIERARCHY.index(identity.trust_level)
        required_idx = _TRUST_HIERARCHY.index(required_trust)

        if agent_idx >= required_idx:
            decision = AuthDecision.ALLOW
            reason = f"Trust level {identity.trust_level.value} meets requirement"
        elif agent_idx == required_idx - 1:
            decision = AuthDecision.CHALLENGE
            reason = "Trust level insufficient, challenge issued"
        else:
            decision = AuthDecision.DENY
            reason = f"Trust level {identity.trust_level.value} below {required_trust.value}"

        request = AuthRequest(
            requester_id=agent_id,
            target_resource=resource,
            action=action,
            decision=decision,
            reason=reason,
        )
        self._auth_log.append(request)
        return request

    def get_auth_log(self, agent_id: str | None = None,
                     decision: AuthDecision | None = None) -> list[AuthRequest]:
        log = self._auth_log
        if agent_id:
            log = [r for r in log if r.requester_id == agent_id]
        if decision:
            log = [r for r in log if r.decision == decision]
        return log

    def get_stats(self) -> IdentityStats:
        by_trust: dict[str, int] = defaultdict(int)
        for identity in self._identities.values():
            by_trust[identity.trust_level.value] += 1

        total_creds = sum(len(c) for c in self._credentials.values())
        total_atts = sum(len(a) for a in self._attestations.values())
        denied = sum(1 for r in self._auth_log if r.decision == AuthDecision.DENY)

        return IdentityStats(
            total_identities=len(self._identities),
            total_credentials=total_creds,
            total_attestations=total_atts,
            auth_requests=len(self._auth_log),
            denied_requests=denied,
            by_trust_level=dict(by_trust),
        )

    def _compute_fingerprint(self, agent_id: str, issuer: str) -> str:
        data = f"{agent_id}:{issuer}:{datetime.now(UTC).isoformat()}"
        return hashlib.sha256(data.encode()).hexdigest()[:32]
