"""Identity: zero-trust agent identity with cryptographic verification and capability attestation."""

from reins.identity.engine import IdentityProvider
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

__all__ = [
    "AgentIdentity",
    "AuthDecision",
    "AuthRequest",
    "CapabilityAttestation",
    "Credential",
    "CredentialKind",
    "IdentityProvider",
    "IdentityStats",
    "TrustLevel",
]
