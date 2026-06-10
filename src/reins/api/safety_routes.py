"""Safety API routes: expose the kernel runtime's safety infrastructure via HTTP."""

from __future__ import annotations

import json
from typing import Any

from aiohttp import web

from reins.event_bus import EventBus
from reins.kernel.runtime import KernelRuntime
from reins.kernel.safety_quorum import SafetyQuorum
from reins.reactive_mesh import ReactionKind


def _json(data: Any, status: int = 200) -> web.Response:
    return web.Response(status=status, content_type="application/json",
                        body=json.dumps(data, default=str))


def add_safety_routes(app: web.Application, runtime: KernelRuntime,
                      quorum: SafetyQuorum | None = None) -> None:
    app["kernel_runtime"] = runtime
    if quorum:
        app["safety_quorum"] = quorum

    app.router.add_post("/safety/evaluate", handle_evaluate)
    app.router.add_get("/safety/quarantine", handle_list_quarantined)
    app.router.add_post("/safety/quarantine/{agent_id}/release", handle_release)
    app.router.add_get("/safety/reactions", handle_reactions)
    app.router.add_get("/safety/stats", handle_stats)
    app.router.add_get("/safety/events", handle_events)
    if quorum:
        app.router.add_post("/safety/quorum/propose", handle_propose)
        app.router.add_post("/safety/quorum/vote", handle_vote)
        app.router.add_post("/safety/quorum/{proposal_id}/resolve", handle_resolve)


async def handle_evaluate(request: web.Request) -> web.Response:
    rt: KernelRuntime = request.app["kernel_runtime"]
    body = await request.json()
    agent_id = body.get("agent_id", "")
    if not agent_id:
        return _json({"error": "agent_id required"}, 400)
    result = await rt.evaluate(agent_id, body)
    return _json({"agent_id": agent_id, "verdict": result.final_verdict.value,
                  "quarantined": rt.mesh.is_quarantined(agent_id)})


async def handle_list_quarantined(request: web.Request) -> web.Response:
    rt: KernelRuntime = request.app["kernel_runtime"]
    return _json({"quarantined": sorted(rt.mesh._quarantined)})


async def handle_release(request: web.Request) -> web.Response:
    rt: KernelRuntime = request.app["kernel_runtime"]
    agent_id = request.match_info["agent_id"]
    released = rt.mesh.release_quarantine(agent_id)
    return _json({"agent_id": agent_id, "released": released})


async def handle_reactions(request: web.Request) -> web.Response:
    rt: KernelRuntime = request.app["kernel_runtime"]
    agent_id = request.query.get("agent_id")
    kind_str = request.query.get("kind")
    kind = ReactionKind(kind_str) if kind_str else None
    reactions = rt.mesh.get_reactions(agent_id=agent_id, kind=kind)
    return _json({"reactions": [r.model_dump(mode="json") for r in reactions]})


async def handle_stats(request: web.Request) -> web.Response:
    rt: KernelRuntime = request.app["kernel_runtime"]
    pipeline_stats = rt.pipeline.get_stats()
    mesh_stats = rt.mesh.get_stats()
    bus_stats = rt.bus.get_stats()
    return _json({
        "pipeline": pipeline_stats.model_dump(mode="json"),
        "mesh": mesh_stats.model_dump(mode="json"),
        "bus": bus_stats.model_dump(mode="json"),
    })


async def handle_events(request: web.Request) -> web.Response:
    rt: KernelRuntime = request.app["kernel_runtime"]
    topic = request.query.get("topic", "safety.*")
    limit = int(request.query.get("limit", "50"))
    events = rt.bus.replay(topic)[-limit:]
    return _json({"events": [{"topic": e.topic, "source": e.source,
                              "payload": e.payload, "ts": str(e.ts)} for e in events]})


async def handle_propose(request: web.Request) -> web.Response:
    quorum: SafetyQuorum = request.app["safety_quorum"]
    body = await request.json()
    pid = quorum.propose_action(body["agent_id"], body["action"], body.get("context"))
    return _json({"proposal_id": pid})


async def handle_vote(request: web.Request) -> web.Response:
    quorum: SafetyQuorum = request.app["safety_quorum"]
    body = await request.json()
    ok = quorum.vote(body["voter_id"], body["proposal_id"], body["approve"],
                     reason=body.get("reason", ""))
    return _json({"accepted": ok})


async def handle_resolve(request: web.Request) -> web.Response:
    quorum: SafetyQuorum = request.app["safety_quorum"]
    pid = request.match_info["proposal_id"]
    decision = quorum.resolve(pid)
    if not decision:
        return _json({"error": "cannot resolve"}, 400)
    return _json({"accepted": decision.accepted, "votes_for": decision.votes_for,
                  "votes_against": decision.votes_against})
