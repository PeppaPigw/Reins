"""Approval domain APIs.

Patterns:
- Use :class:`ApprovalLedger` for requests, grants, rejections, and audit queries.
- Use :meth:`ApprovalLedger.delegate` to grant a bounded actor temporary approval
  authority for matching capabilities and resources.
- Keep existing imports from ``reins.policy.approval.ledger`` working through the
  compatibility shim while preferring this package for new code.
"""

from reins.approval.audit import ApprovalAuditEntry, ApprovalAuditLog
from reins.approval.delegation import ApprovalDelegation, ApprovalDelegationLedger
from reins.approval.ledger import (
    ApprovalGrant,
    ApprovalLedger,
    ApprovalRejection,
    ApprovalRequest,
    ApprovalStatusEntry,
    EffectDescriptor,
)

__all__ = [
    "ApprovalAuditEntry",
    "ApprovalAuditLog",
    "ApprovalDelegation",
    "ApprovalDelegationLedger",
    "ApprovalGrant",
    "ApprovalLedger",
    "ApprovalRejection",
    "ApprovalRequest",
    "ApprovalStatusEntry",
    "EffectDescriptor",
]
