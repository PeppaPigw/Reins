"""Reins REST API — command proposal and approval routes."""

from __future__ import annotations

import logging

from aiohttp import web
from pydantic import ValidationError

from reins.api.models import (
    ApprovalRequest,
    RejectionRequest,
    SubmitCommandRequest,
)
from reins.api.registry import RunRegistry
from reins.api.routes import _error, _json, _validation_error

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# POST /runs/{id}/commands  — submit a CommandProposal
# ---------------------------------------------------------------------------
async def handle_submit_command(request: web.Request) -> web.Response:
    """Submit an untrusted CommandProposal from a model adapter.

    Body fields:
      kind: str               — capability name (e.g. "fs.read")
      args: dict              — capability-specific arguments
      source: str             — "model" | "human" | "hook" | "skill"
      rationale_ref: str|null — artifact ref for rationale
      idempotency_key: str    — optional, prevents double-submission
    """
    reg: RunRegistry = request.app["registry"]
    run_id = request.match_info["id"]
    try:
        body = await request.json()
    except Exception:
        return _error("invalid JSON body")

    try:
        validated = SubmitCommandRequest.model_validate(body)
    except ValidationError as exc:
        return _validation_error(exc)

    try:
        result = await reg.submit_command(
            run_id=run_id,
            kind=validated.kind,
            args=validated.args,
            source=validated.source,
            rationale_ref=validated.rationale_ref,
            idempotency_key=validated.idempotency_key,
            evaluate=validated.evaluate,
        )
    except KeyError:
        return _error(f"run not found: {run_id}", 404)
    except Exception as exc:
        log.exception("submit_command failed")
        return _error(str(exc), 500)

    return _json(result)


# ---------------------------------------------------------------------------
# POST /runs/{id}/approve
# ---------------------------------------------------------------------------
async def handle_approve(request: web.Request) -> web.Response:
    """Approve a pending effect by request_id."""
    reg: RunRegistry = request.app["registry"]
    run_id = request.match_info["id"]
    try:
        body = await request.json()
    except Exception:
        return _error("invalid JSON body")

    try:
        validated = ApprovalRequest.model_validate(body)
    except ValidationError as exc:
        return _validation_error(exc)

    try:
        grant = await reg.approve(
            run_id, validated.request_id, granted_by=validated.granted_by
        )
    except KeyError:
        return _error(f"run not found: {run_id}", 404)
    except Exception as exc:
        log.exception("approve failed")
        return _error(str(exc), 500)

    if grant is None:
        return _error(
            "approval request not found or ledger not configured", 404
        )
    return _json(
        {"grant_id": grant.grant_id, "capability": grant.capability}
    )


# ---------------------------------------------------------------------------
# POST /runs/{id}/reject
# ---------------------------------------------------------------------------
async def handle_reject(request: web.Request) -> web.Response:
    """Reject a pending effect."""
    reg: RunRegistry = request.app["registry"]
    run_id = request.match_info["id"]
    try:
        body = await request.json()
    except Exception:
        return _error("invalid JSON body")

    try:
        validated = RejectionRequest.model_validate(body)
    except ValidationError as exc:
        return _validation_error(exc)

    try:
        rejection = await reg.reject(
            run_id,
            validated.request_id,
            reason=validated.reason,
            rejected_by=validated.rejected_by,
        )
    except KeyError:
        return _error(f"run not found: {run_id}", 404)
    except Exception as exc:
        log.exception("reject failed")
        return _error(str(exc), 500)

    if rejection is None:
        return _error(
            "approval request not found or ledger not configured", 404
        )
    return _json(
        {"request_id": rejection.request_id, "reason": rejection.reason}
    )


# ---------------------------------------------------------------------------
# POST /runs/{id}/abort
# ---------------------------------------------------------------------------
async def handle_abort(request: web.Request) -> web.Response:
    """Abort a run (kill switch)."""
    reg: RunRegistry = request.app["registry"]
    run_id = request.match_info["id"]
    try:
        body = await request.json()
    except Exception:
        body = {}
    reason = body.get("reason", "aborted by operator")

    try:
        state = await reg.abort(run_id, reason)
    except KeyError:
        return _error(f"run not found: {run_id}", 404)
    except Exception as exc:
        log.exception("abort failed")
        return _error(str(exc), 500)

    return _json({"run_id": state.run_id, "status": state.status.value})


# ---------------------------------------------------------------------------
# POST /runs/{id}/resume
# ---------------------------------------------------------------------------
async def handle_resume(request: web.Request) -> web.Response:
    """Resume a dehydrated run from a checkpoint."""
    reg: RunRegistry = request.app["registry"]
    run_id = request.match_info["id"]
    try:
        body = await request.json()
    except Exception:
        body = {}
    checkpoint_id = body.get("checkpoint_id")

    try:
        state = await reg.resume(run_id, checkpoint_id)
    except KeyError:
        return _error(f"run not found: {run_id}", 404)
    except FileNotFoundError as exc:
        return _error(f"checkpoint not found: {exc}", 404)
    except Exception as exc:
        log.exception("resume failed")
        return _error(str(exc), 500)

    return _json(
        {
            "run_id": state.run_id,
            "status": state.status.value,
            "last_checkpoint_id": state.last_checkpoint_id,
        }
    )
