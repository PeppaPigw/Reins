"""Tests for compositional safety verification engine."""

from __future__ import annotations

import pytest

from reins.composability import (
    AgentContract,
    ComposabilityEngine,
    ComposabilityStats,
    Composition,
    CompositionKind,
    CompositionStatus,
    InterferenceKind,
    InterferenceReport,
    SafetyComposition,
    SafetyRelation,
)


@pytest.fixture
def engine() -> ComposabilityEngine:
    return ComposabilityEngine()


def test_register_contract(engine):
    contract = engine.register_contract(
        "agent-1",
        requires={"file_read"},
        provides={"analysis"},
        modifies={"state_db"},
        invariants=["no_data_loss"],
    )
    assert contract.agent_id == "agent-1"
    assert "file_read" in contract.requires
    assert "analysis" in contract.provides


def test_get_contract(engine):
    engine.register_contract("a", requires={"x"})
    assert engine.get_contract("a") is not None
    assert engine.get_contract("missing") is None


def test_compose_sequential(engine):
    comp = engine.compose("pipeline", ["a", "b", "c"],
                          kind=CompositionKind.SEQUENTIAL)
    assert comp.name == "pipeline"
    assert comp.kind == CompositionKind.SEQUENTIAL
    assert comp.agents == ["a", "b", "c"]
    assert comp.status == CompositionStatus.UNVERIFIED


def test_compose_parallel(engine):
    comp = engine.compose("fan_out", ["a", "b"], kind=CompositionKind.PARALLEL)
    assert comp.kind == CompositionKind.PARALLEL


def test_interference_no_conflict(engine):
    engine.register_contract("a", requires={"x"}, modifies={"y"})
    engine.register_contract("b", requires={"z"}, modifies={"w"})
    report = engine.check_interference("a", "b")
    assert report.kind == InterferenceKind.NONE


def test_interference_write_write(engine):
    engine.register_contract("a", modifies={"shared_state"})
    engine.register_contract("b", modifies={"shared_state"})
    report = engine.check_interference("a", "b")
    assert report.kind == InterferenceKind.WRITE_WRITE
    assert "shared_state" in report.shared_resources


def test_interference_read_write(engine):
    engine.register_contract("a", requires={"config"}, modifies=set())
    engine.register_contract("b", requires=set(), modifies={"config"})
    report = engine.check_interference("a", "b")
    assert report.kind == InterferenceKind.READ_WRITE
    assert "config" in report.shared_resources


def test_interference_missing_contract(engine):
    engine.register_contract("a", modifies={"x"})
    report = engine.check_interference("a", "unknown")
    assert report.kind == InterferenceKind.NONE
    assert "Missing" in report.message


def test_check_dependencies_satisfied(engine):
    engine.register_contract("a", provides={"data"}, requires=set())
    engine.register_contract("b", requires={"data"}, provides=set())
    comp = engine.compose("seq", ["a", "b"], kind=CompositionKind.SEQUENTIAL)
    issues = engine.check_dependencies(comp.composition_id)
    assert issues == []


def test_check_dependencies_unmet(engine):
    engine.register_contract("a", provides={"x"}, requires=set())
    engine.register_contract("b", requires={"y"}, provides=set())
    comp = engine.compose("seq", ["a", "b"], kind=CompositionKind.SEQUENTIAL)
    issues = engine.check_dependencies(comp.composition_id)
    assert len(issues) == 1
    assert "y" in issues[0]


def test_check_dependencies_missing_composition(engine):
    issues = engine.check_dependencies("nonexistent")
    assert "not found" in issues[0]


def test_check_dependencies_no_contract(engine):
    comp = engine.compose("seq", ["unknown_agent"], kind=CompositionKind.SEQUENTIAL)
    issues = engine.check_dependencies(comp.composition_id)
    assert "No contract" in issues[0]


def test_verify_composition_safe(engine):
    engine.register_contract("a", provides={"data"}, modifies={"log"},
                             invariants=["audit_trail"])
    engine.register_contract("b", requires={"data"}, modifies={"output"},
                             invariants=["idempotent"])
    comp = engine.compose("safe_pipe", ["a", "b"])
    proof = engine.verify_composition(comp.composition_id)
    assert proof.relation == SafetyRelation.PRESERVES
    assert "audit_trail" in proof.preserved_invariants
    assert "idempotent" in proof.preserved_invariants
    updated = engine.get_composition(comp.composition_id)
    assert updated.status == CompositionStatus.SAFE


def test_verify_composition_violated(engine):
    engine.register_contract("a", modifies={"shared"}, invariants=["consistency"])
    engine.register_contract("b", modifies={"shared"}, invariants=["consistency"])
    comp = engine.compose("conflict", ["a", "b"], kind=CompositionKind.PARALLEL)
    proof = engine.verify_composition(comp.composition_id)
    assert proof.relation == SafetyRelation.VIOLATES
    assert "consistency" in proof.violated_invariants
    updated = engine.get_composition(comp.composition_id)
    assert updated.status == CompositionStatus.UNSAFE


def test_verify_composition_weakened(engine):
    engine.register_contract("a", requires={"config"}, modifies=set(),
                             invariants=["config_stable"])
    engine.register_contract("b", modifies={"config"}, invariants=[])
    comp = engine.compose("weak", ["a", "b"])
    proof = engine.verify_composition(comp.composition_id)
    assert proof.relation == SafetyRelation.WEAKENS
    assert "config_stable" in proof.weakened_invariants


def test_verify_composition_not_found(engine):
    proof = engine.verify_composition("missing")
    assert proof.relation == SafetyRelation.UNKNOWN


def test_get_proofs(engine):
    engine.register_contract("a", provides={"x"}, modifies=set())
    comp = engine.compose("test", ["a"])
    engine.verify_composition(comp.composition_id)
    assert len(engine.get_proofs()) == 1
    assert len(engine.get_proofs(composition_id=comp.composition_id)) == 1
    assert len(engine.get_proofs(composition_id="other")) == 0


def test_get_interferences(engine):
    engine.register_contract("a", modifies={"x"})
    engine.register_contract("b", modifies={"x"})
    engine.check_interference("a", "b")
    assert len(engine.get_interferences()) == 1
    assert len(engine.get_interferences(agent_id="a")) == 1
    assert len(engine.get_interferences(agent_id="c")) == 0


def test_stats_empty(engine):
    stats = engine.get_stats()
    assert stats.total_contracts == 0
    assert stats.total_compositions == 0


def test_stats_populated(engine):
    engine.register_contract("a", modifies={"x"}, invariants=["safe"])
    engine.register_contract("b", modifies={"x"}, invariants=["safe"])
    comp = engine.compose("test", ["a", "b"], kind=CompositionKind.PARALLEL)
    engine.verify_composition(comp.composition_id)
    stats = engine.get_stats()
    assert stats.total_contracts == 2
    assert stats.total_compositions == 1
    assert stats.unsafe_compositions == 1
    assert stats.total_interferences == 1
    assert stats.by_kind["parallel"] == 1


def test_composition_kinds_all(engine):
    for kind in CompositionKind:
        comp = engine.compose(f"test_{kind.value}", ["a"], kind=kind)
        assert comp.kind == kind


def test_multiple_agents_chain(engine):
    engine.register_contract("fetch", provides={"raw_data"}, modifies=set())
    engine.register_contract("transform", requires={"raw_data"},
                             provides={"clean_data"}, modifies=set())
    engine.register_contract("load", requires={"clean_data"}, modifies={"database"})
    comp = engine.compose("etl", ["fetch", "transform", "load"],
                          kind=CompositionKind.PIPELINE)
    issues = engine.check_dependencies(comp.composition_id)
    assert issues == []
    proof = engine.verify_composition(comp.composition_id)
    assert proof.relation == SafetyRelation.PRESERVES
