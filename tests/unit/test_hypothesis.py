"""Tests for Bayesian hypothesis testing engine."""

from __future__ import annotations

import pytest

from reins.hypothesis import (
    Evidence,
    EvidenceKind,
    Hypothesis,
    HypothesisEngine,
    HypothesisStatus,
    TestOutcome,
)


@pytest.fixture
def engine() -> HypothesisEngine:
    return HypothesisEngine(support_threshold=0.8, refutation_threshold=0.2, min_evidence=3)


def test_propose_hypothesis(engine):
    h = engine.propose("The API is rate-limited", prior=0.5)
    assert h.statement == "The API is rate-limited"
    assert h.prior_probability == 0.5
    assert h.posterior_probability == 0.5


def test_propose_with_domain(engine):
    h = engine.propose("Cache improves latency", domain="performance")
    assert h.domain == "performance"


def test_add_confirming_evidence(engine):
    h = engine.propose("Bug is in auth module", prior=0.5)
    engine.add_evidence(h.hypothesis_id, EvidenceKind.CONFIRMING,
                        "Stack trace points to auth", likelihood_ratio=3.0)
    updated = engine.get_hypothesis(h.hypothesis_id)
    assert updated.posterior_probability > 0.5


def test_add_disconfirming_evidence(engine):
    h = engine.propose("Memory leak in parser", prior=0.5)
    engine.add_evidence(h.hypothesis_id, EvidenceKind.DISCONFIRMING,
                        "Heap stable after parsing", likelihood_ratio=0.3)
    updated = engine.get_hypothesis(h.hypothesis_id)
    assert updated.posterior_probability < 0.5


def test_evidence_for_nonexistent(engine):
    result = engine.add_evidence("fake", EvidenceKind.CONFIRMING, "x")
    assert result is None


def test_multiple_evidence_accumulates(engine):
    h = engine.propose("Timeout is network-related", prior=0.5)
    for _ in range(4):
        engine.add_evidence(h.hypothesis_id, EvidenceKind.CONFIRMING,
                            "Packet loss detected", likelihood_ratio=2.5)
    updated = engine.get_hypothesis(h.hypothesis_id)
    assert updated.posterior_probability > 0.9


def test_status_transitions_to_supported(engine):
    h = engine.propose("DB is bottleneck", prior=0.6)
    for _ in range(3):
        engine.add_evidence(h.hypothesis_id, EvidenceKind.CONFIRMING,
                            "Slow query log", likelihood_ratio=3.0)
    updated = engine.get_hypothesis(h.hypothesis_id)
    assert updated.status == HypothesisStatus.SUPPORTED


def test_status_transitions_to_refuted(engine):
    h = engine.propose("Frontend causes lag", prior=0.4)
    for _ in range(3):
        engine.add_evidence(h.hypothesis_id, EvidenceKind.DISCONFIRMING,
                            "Frontend renders in <50ms", likelihood_ratio=0.2)
    updated = engine.get_hypothesis(h.hypothesis_id)
    assert updated.status == HypothesisStatus.REFUTED


def test_status_testing_with_insufficient_evidence(engine):
    h = engine.propose("Something", prior=0.5)
    engine.add_evidence(h.hypothesis_id, EvidenceKind.CONFIRMING, "one", likelihood_ratio=2.0)
    updated = engine.get_hypothesis(h.hypothesis_id)
    assert updated.status == HypothesisStatus.TESTING


def test_run_experiment_pass(engine):
    h = engine.propose("Feature works", prior=0.5)
    exp = engine.run_experiment(h.hypothesis_id, "Integration test", TestOutcome.PASS)
    assert exp is not None
    updated = engine.get_hypothesis(h.hypothesis_id)
    assert updated.posterior_probability > 0.5


def test_run_experiment_fail(engine):
    h = engine.propose("Config is correct", prior=0.6)
    engine.run_experiment(h.hypothesis_id, "Validation check", TestOutcome.FAIL)
    updated = engine.get_hypothesis(h.hypothesis_id)
    assert updated.posterior_probability < 0.6


def test_run_experiment_nonexistent(engine):
    result = engine.run_experiment("fake", "test", TestOutcome.PASS)
    assert result is None


def test_get_evidence_for(engine):
    h = engine.propose("H1", prior=0.5)
    engine.add_evidence(h.hypothesis_id, EvidenceKind.CONFIRMING, "e1")
    engine.add_evidence(h.hypothesis_id, EvidenceKind.NEUTRAL, "e2")
    evidence = engine.get_evidence_for(h.hypothesis_id)
    assert len(evidence) == 2


def test_competing_hypotheses(engine):
    h1 = engine.propose("Cause A", prior=0.5, domain="bug")
    h2 = engine.propose("Cause B", prior=0.5, domain="bug")
    engine.add_evidence(h1.hypothesis_id, EvidenceKind.CONFIRMING, "supports A", likelihood_ratio=4.0)
    competing = engine.get_competing("bug")
    assert len(competing) == 2
    assert competing[0].hypothesis_id == h1.hypothesis_id


def test_best_hypothesis(engine):
    h1 = engine.propose("X", prior=0.3, domain="perf")
    h2 = engine.propose("Y", prior=0.7, domain="perf")
    best = engine.get_best_hypothesis("perf")
    assert best.hypothesis_id == h2.hypothesis_id


def test_best_hypothesis_empty_domain(engine):
    assert engine.get_best_hypothesis("nonexistent") is None


def test_get_supported(engine):
    h = engine.propose("Strong claim", prior=0.7)
    for _ in range(4):
        engine.add_evidence(h.hypothesis_id, EvidenceKind.CONFIRMING, "proof", likelihood_ratio=3.0)
    supported = engine.get_supported()
    assert len(supported) >= 1


def test_get_refuted(engine):
    h = engine.propose("Weak claim", prior=0.3)
    for _ in range(3):
        engine.add_evidence(h.hypothesis_id, EvidenceKind.DISCONFIRMING, "counter", likelihood_ratio=0.2)
    refuted = engine.get_refuted()
    assert len(refuted) >= 1


def test_posterior_bounded(engine):
    h = engine.propose("Extreme", prior=0.99)
    for _ in range(10):
        engine.add_evidence(h.hypothesis_id, EvidenceKind.CONFIRMING, "more", likelihood_ratio=10.0)
    updated = engine.get_hypothesis(h.hypothesis_id)
    assert updated.posterior_probability <= 0.99


def test_stats_empty():
    e = HypothesisEngine()
    stats = e.get_stats()
    assert stats.total_hypotheses == 0
    assert stats.avg_posterior == 0.5


def test_stats_with_data(engine):
    h = engine.propose("Test", prior=0.5)
    engine.add_evidence(h.hypothesis_id, EvidenceKind.CONFIRMING, "e1", likelihood_ratio=2.0)
    engine.run_experiment(h.hypothesis_id, "exp1", TestOutcome.PASS)
    stats = engine.get_stats()
    assert stats.total_hypotheses == 1
    assert stats.total_evidence == 2
    assert stats.total_experiments == 1
