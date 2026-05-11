"""Approval flow coordination between Slack interactive messages and the kernel.

Manages the lifecycle of approval requests: creation, notification via Slack,
response handling, and expiration of stale requests.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum

from reins.integrations.slack import SlackClient


# ---------------------------------------------------------------------------
# Enums and data models
# ---------------------------------------------------------------------------


class ApprovalStatus(str, Enum):
    """Lifecycle states for an approval request."""

    pending = "pending"
    approved = "approved"
    denied = "denied"
    expired = "expired"


@dataclass
class ApprovalRequest:
    """A tracked approval request."""

    request_id: str
    title: str
    description: str
    requester: str
    risk_level: str
    status: ApprovalStatus = ApprovalStatus.pending
    created_at: str = ""
    responded_at: str | None = None
    responder: str | None = None

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass(frozen=True)
class ApprovalResponse:
    """Immutable record of an approval decision."""

    request_id: str
    approved: bool
    responder: str
    timestamp: str
    comment: str | None = None


# ---------------------------------------------------------------------------
# Approval manager
# ---------------------------------------------------------------------------


class ApprovalManager:
    """Coordinates approval request/response lifecycle.

    Optionally sends interactive Slack messages when a SlackClient is provided.
    """

    def __init__(self, slack_client: SlackClient | None = None):
        self._slack_client = slack_client
        self._pending: dict[str, ApprovalRequest] = {}
        self._counter: int = 0

    def create_request(
        self,
        title: str,
        description: str,
        requester: str,
        risk_level: str = "medium",
    ) -> ApprovalRequest:
        """Create an approval request and optionally notify Slack."""
        self._counter += 1
        request_id = f"apr-{self._counter:04d}"

        req = ApprovalRequest(
            request_id=request_id,
            title=title,
            description=description,
            requester=requester,
            risk_level=risk_level,
        )
        self._pending[request_id] = req

        if self._slack_client is not None:
            self._slack_client.send_approval_request(
                request_id=request_id,
                title=title,
                description=description,
                requester=requester,
                risk_level=risk_level,
            )

        return req

    def handle_response(
        self,
        request_id: str,
        approved: bool,
        responder: str,
        comment: str | None = None,
    ) -> ApprovalResponse:
        """Record an approval decision and update the request status."""
        req = self._pending.get(request_id)
        if req is None:
            raise ValueError(f"Unknown request: {request_id}")

        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        req.status = ApprovalStatus.approved if approved else ApprovalStatus.denied
        req.responded_at = timestamp
        req.responder = responder

        return ApprovalResponse(
            request_id=request_id,
            approved=approved,
            responder=responder,
            timestamp=timestamp,
            comment=comment,
        )

    def get_pending(self) -> list[ApprovalRequest]:
        """Return all requests still in pending status."""
        return [r for r in self._pending.values() if r.status == ApprovalStatus.pending]

    def get_request(self, request_id: str) -> ApprovalRequest | None:
        """Retrieve a request by ID, or None if not found."""
        return self._pending.get(request_id)

    def is_approved(self, request_id: str) -> bool:
        """Check whether a request has been approved."""
        req = self._pending.get(request_id)
        if req is None:
            return False
        return req.status == ApprovalStatus.approved

    def expire_old_requests(self, max_age_seconds: float = 3600.0) -> list[str]:
        """Expire pending requests older than *max_age_seconds*.

        Returns the list of request IDs that were expired.
        """
        now = time.time()
        expired_ids: list[str] = []

        for req in list(self._pending.values()):
            if req.status != ApprovalStatus.pending:
                continue
            created_ts = time.mktime(time.strptime(req.created_at, "%Y-%m-%dT%H:%M:%SZ"))
            if now - created_ts >= max_age_seconds:
                req.status = ApprovalStatus.expired
                expired_ids.append(req.request_id)

        return expired_ids
