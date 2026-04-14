"""Reins REST API — run lifecycle routes.

Routes implemented (SystemDesign §17.1):
  POST /runs               — create a run (intake)
  GET  /runs/{id}          — get run state
  POST /runs/{id}/resume   — resume a dehydrated run
  POST /runs/{id}/abort    — abort (kill switch)
  POST /runs/{id}/approve  — approve a pending effect
  POST /runs/{id}/reject   — reject a pending effect
  GET  /runs/{id}/timeline — get the run timeline
  POST /runs/{id}/commands — submit a CommandProposal from a model adapter

The server holds one RunOrchestrator per run_id.  For a real
deployment this would back-end to a durable registry; for v1
it is in-process with file-backed journal/snapshot/checkpoint stores.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from aiohttp import web

from reins.api.registry import RunRegistry

log = logging.getLogger(__name__)


def _json(data: Any, status: int = 200) -> web.Response:
    return web.Response(
        status=status,
        content_type="application/json",
        body=json.dumps(data, default=str),
    )


def _error(msg: str, status: int = 400) -> web.Response:
    return _json({"error": msg}, status)


# ---------------------------------------------------------------------------
# POST /runs
# ---------------------------------------------------------------------------
async def handle_create_run(request: web.Request) -> web.Response:
    """Create a new run from an intent.  Body: IntentEnvelope fields."""
    reg: RunRegistry = request.app["registry"]
    try:
        body = await request.json()
    except Exception:
        return _error("invalid JSON body")

    objective = body.get("objective", "").strip()
    if not objective:
        return _error("objective is required")

    try:
        state = await reg.create_run(
            objective=objective,
            issuer=body.get("issuer", "user"),
            constraints=body.get("constraints", []),
            requested_capabilities=body.get("requested_capabilities", []),
        )
    except Exception as exc:
        log.exception("create_run failed")
        return _error(str(exc), 500)

    return _json({"run_id": state.run_id, "status": state.status.value}, 201)


# ---------------------------------------------------------------------------
# GET /runs/{id}
# ---------------------------------------------------------------------------
async def handle_get_run(request: web.Request) -> web.Response:
    reg: RunRegistry = request.app["registry"]
    run_id = request.match_info["id"]
    state = reg.get_state(run_id)
    if state is None:
        return _error(f"run not found: {run_id}", 404)
    return _json({
        "run_id": state.run_id,
        "status": state.status.value,
        "last_failure_class": state.last_failure_class.value if state.last_failure_class else None,
        "pending_approvals": list(state.pending_approvals),
        "active_grants": [
            {"grant_id": g.grant_id, "capability": g.capability, "scope": g.scope}
            for g in state.active_grants
        ],
        "open_handles": [
            {"handle_id": h.handle_id, "adapter_kind": h.adapter_kind}
            for h in state.open_handles
        ],
        "last_checkpoint_id": state.last_checkpoint_id,
        "snapshot_id": state.snapshot_id,
    })


# ---------------------------------------------------------------------------
# GET /runs/{id}/timeline
# ---------------------------------------------------------------------------
async def handle_get_timeline(request: web.Request) -> web.Response:
    reg: RunRegistry = request.app["registry"]
    run_id = request.match_info["id"]
    try:
        summary = await reg.get_timeline(run_id)
    except KeyError:
        return _error(f"run not found: {run_id}", 404)
    except Exception as exc:
        log.exception("get_timeline failed")
        return _error(str(exc), 500)
    return _json(summary)
