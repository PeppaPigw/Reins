from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import ulid
from pydantic import BaseModel, ConfigDict, Field


def _new_ulid() -> str:
    return str(ulid.new())


def _utc_now() -> datetime:
    return datetime.now(UTC)


class TrustLevel(str, Enum):
    UNTRUSTED = "untrusted"
    VERIFIED = "verified"
    ATTESTED = "attested"
    PRIVILEGED = "privileged"
    SYSTEM = "system"


class CredentialKind(str, Enum):
    API_KEY = "api_key"
    CERTIFICATE = "certificate"
    TOKEN = "token"
    SIGNATURE = "signature"
    ATTESTATION = "attestation"


class AuthDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    CHALLENGE = "challenge"
    ESCALATE = "escalate"


class AgentIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    identity_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    display_name: str = ""
    fingerprint: str = ""
    trust_level: TrustLevel = TrustLevel.UNTRUSTED
    capabilities: tuple[str, ...] = ()
    issuer: str = ""
    issued_at: datetime = Field(default_factory=_utc_now)
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Credential(BaseModel):
    model_config = ConfigDict(frozen=True)

    credential_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    kind: CredentialKind
    value_hash: str = ""
    issued_at: datetime = Field(default_factory=_utc_now)
    expires_at: datetime | None = None
    revoked: bool = False


class CapabilityAttestation(BaseModel):
    model_config = ConfigDict(frozen=True)

    attestation_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    capability: str
    attested_by: str = ""
    evidence: str = ""
    valid_until: datetime | None = None
    checksum: str = ""


class AuthRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str = Field(default_factory=_new_ulid)
    requester_id: str
    target_resource: str
    action: str
    decision: AuthDecision = AuthDecision.DENY
    reason: str = ""
    timestamp: datetime = Field(default_factory=_utc_now)


class IdentityStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_identities: int = 0
    total_credentials: int = 0
    total_attestations: int = 0
    auth_requests: int = 0
    denied_requests: int = 0
    by_trust_level: dict[str, int] = Field(default_factory=dict)
