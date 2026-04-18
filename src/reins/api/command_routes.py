"""Reins REST API — command proposal and approval routes."""

from __future__ import annotations

import logging

from aiohttp import web

from reins.api.registry import RunRegistry
from reins.api.routes import _error, _json

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

    kind = body.get("kind", "").strip()
    if not kind:
        return _error("kind is required")

    try:
        result = await reg.submit_command(
            run_id=run_id,
            kind=kind,
            args=body.get("args", {}),
            source=body.get("source", "model"),
            rationale_ref=body.get("rationale_ref"),
            idempotency_key=body.get("idempotency_key"),
            evaluate=body.get("evaluate", False),
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

    request_id = body.get("request_id", "").strip()
    if not request_id:
        return _error("request_id is required")

    try:
        grant = await reg.approve(
            run_id, request_id, granted_by=body.get("granted_by", "human")
        )
    except KeyError:
        return _error(f"run not found: {run_id}", 404)
    except Exception as exc:
        log.exception("approve failed")
        return _error(str(exc), 500)

    if grant is None:
        return _error("approval request not found or ledger not configured", 404)
    return _json({"grant_id": grant.grant_id, "capability": grant.capability})


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

    request_id = body.get("request_id", "").strip()
    reason = body.get("reason", "rejected by human")
    if not request_id:
        return _error("request_id is required")

    try:
        rejection = await reg.reject(
            run_id,
            request_id,
            reason=reason,
            rejected_by=body.get("rejected_by", "human"),
        )
    except KeyError:
        return _error(f"run not found: {run_id}", 404)
    except Exception as exc:
        log.exception("reject failed")
        return _error(str(exc), 500)

    if rejection is None:
        return _error("approval request not found or ledger not configured", 404)
    return _json({"request_id": rejection.request_id, "reason": rejection.reason})


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
