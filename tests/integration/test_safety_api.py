"""Tests for safety API routes — direct handler invocation."""

from __future__ import annotations

import json
from typing import Any

import pytest

from reins.api.safety_routes import (
    add_safety_routes,
    handle_evaluate,
    handle_events,
    handle_list_quarantined,
    handle_propose,
    handle_reactions,
    handle_release,
    handle_resolve,
    handle_stats,
    handle_vote,
)
from reins.consensus import ConsensusProtocol
from reins.identity import IdentityProvider, TrustLevel
from reins.kernel.runtime import KernelRuntime
from reins.kernel.safety_quorum import SafetyQuorum
from reins.policy_dsl import ConditionOp, PolicyDSLEngine, PolicyScope, RuleEffect
from reins.reactive_mesh import ReactionKind, TriggerCondition
from reins.safety_pipeline import PipelineStage
from reins.safety_pipeline.adapters import make_identity_stage, make_policy_stage


class FakeRequest:
    def __init__(self, app: dict, body: dict | None = None, match_info: dict | None = None,
                 query: dict | None = None):
        self.app = app
        self._body = body or {}
        self.match_info = match_info or {}
        self.query = query or {}

    async def json(self) -> dict:
        return self._body


def _parse(resp) -> dict:
    return json.loads(resp.body._value)


@pytest.fixture
def runtime():
    rt = KernelRuntime()
    identity = IdentityProvider()
    identity.register_identity("agent-1", display_name="Agent")
    identity.elevate_trust("agent-1", TrustLevel.VERIFIED)

    policy = PolicyDSLEngine()
    policy.add_rule(name="no-delete", effect=RuleEffect.DENY, scope=PolicyScope.ACTION,
                    conditions=[{"field": "action", "op": ConditionOp.EQUALS, "value": "delete"}])

    rt.pipeline.register_stage(PipelineStage.IDENTITY, make_identity_stage(identity))
    rt.pipeline.register_stage(PipelineStage.POLICY, make_policy_stage(policy))

    rt.mesh.add_rule("quarantine", TriggerCondition.EVENT_MATCH,
                     "safety.denied", ReactionKind.QUARANTINE, cooldown_seconds=0.0)
    rt.boot()
    return rt


@pytest.fixture
def quorum(runtime):
    q = SafetyQuorum(runtime.bus, protocol=ConsensusProtocol.MAJORITY)
    q.register_voter("voter-1")
    q.register_voter("voter-2")
    return q


@pytest.fixture
def app(runtime, quorum):
    return {"kernel_runtime": runtime, "safety_quorum": quorum}


@pytest.mark.asyncio
async def test_evaluate_pass(app):
    req = FakeRequest(app, {"agent_id": "agent-1", "action": "read"})
    resp = await handle_evaluate(req)
    data = _parse(resp)
    assert data["verdict"] == "pass"
    assert data["quarantined"] is False


@pytest.mark.asyncio
async def test_evaluate_deny_quarantines(app):
    req = FakeRequest(app, {"agent_id": "unknown", "action": "x"})
    resp = await handle_evaluate(req)
    data = _parse(resp)
    assert data["verdict"] == "fail"
    assert data["quarantined"] is True


@pytest.mark.asyncio
async def test_quarantine_list(app):
    await handle_evaluate(FakeRequest(app, {"agent_id": "bad", "action": "x"}))
    req = FakeRequest(app)
    resp = await handle_list_quarantined(req)
    data = _parse(resp)
    assert "bad" in data["quarantined"]


@pytest.mark.asyncio
async def test_release_quarantine(app):
    await handle_evaluate(FakeRequest(app, {"agent_id": "bad2", "action": "x"}))
    req = FakeRequest(app, match_info={"agent_id": "bad2"})
    resp = await handle_release(req)
    data = _parse(resp)
    assert data["released"] is True


@pytest.mark.asyncio
async def test_stats(app):
    await handle_evaluate(FakeRequest(app, {"agent_id": "agent-1", "action": "read"}))
    resp = await handle_stats(FakeRequest(app))
    data = _parse(resp)
    assert "pipeline" in data
    assert "mesh" in data
    assert "bus" in data


@pytest.mark.asyncio
async def test_events(app):
    await handle_evaluate(FakeRequest(app, {"agent_id": "agent-1", "action": "read"}))
    req = FakeRequest(app, query={"topic": "safety.*"})
    resp = await handle_events(req)
    data = _parse(resp)
    assert len(data["events"]) >= 1


@pytest.mark.asyncio
async def test_quorum_propose_vote_resolve(app):
    req = FakeRequest(app, {"agent_id": "agent-x", "action": "deploy"})
    resp = await handle_propose(req)
    pid = _parse(resp)["proposal_id"]

    await handle_vote(FakeRequest(app, {"voter_id": "voter-1", "proposal_id": pid, "approve": True}))
    await handle_vote(FakeRequest(app, {"voter_id": "voter-2", "proposal_id": pid, "approve": True}))

    req = FakeRequest(app, match_info={"proposal_id": pid})
    resp = await handle_resolve(req)
    data = _parse(resp)
    assert data["accepted"] is True


@pytest.mark.asyncio
async def test_reactions(app):
    await handle_evaluate(FakeRequest(app, {"agent_id": "rogue", "action": "x"}))
    req = FakeRequest(app, query={"agent_id": "rogue"})
    resp = await handle_reactions(req)
    data = _parse(resp)
    assert len(data["reactions"]) >= 1
