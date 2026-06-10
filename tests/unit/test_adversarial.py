"""Tests for adversarial testing with automated red-teaming."""

from __future__ import annotations

import pytest

from reins.adversarial import (
    AdversarialStats,
    AdversarialTester,
    AttackCategory,
    AttackPattern,
    AttackSeverity,
    ProbeAttempt,
    ProbeResult,
    RobustnessScore,
    Vulnerability,
)


@pytest.fixture
def tester() -> AdversarialTester:
    return AdversarialTester()


def test_default_patterns_registered(tester):
    patterns = tester.get_patterns()
    assert len(patterns) >= 9


def test_get_patterns_by_category(tester):
    patterns = tester.get_patterns(category=AttackCategory.PROMPT_INJECTION)
    assert len(patterns) >= 2
    assert all(p.category == AttackCategory.PROMPT_INJECTION for p in patterns)


def test_register_custom_pattern(tester):
    pattern = AttackPattern(
        category=AttackCategory.RESOURCE_ABUSE,
        name="memory-bomb",
        description="Attempts to exhaust memory",
        severity=AttackSeverity.HIGH,
    )
    registered = tester.register_pattern(pattern)
    assert tester.get_pattern(registered.pattern_id) is not None


def test_get_pattern_not_found(tester):
    assert tester.get_pattern("nonexistent") is None


def test_record_probe_blocked(tester):
    patterns = tester.get_patterns(category=AttackCategory.PROMPT_INJECTION)
    pattern = patterns[0]
    attempt = tester.record_probe(
        pattern.pattern_id, "agent-1", ProbeResult.BLOCKED, response="Request denied"
    )
    assert attempt.result == ProbeResult.BLOCKED
    assert attempt.target_id == "agent-1"


def test_record_probe_creates_vulnerability_on_bypass(tester):
    patterns = tester.get_patterns(category=AttackCategory.JAILBREAK)
    pattern = patterns[0]
    tester.record_probe(
        pattern.pattern_id, "agent-1", ProbeResult.FULL_BYPASS,
        response="I'll ignore my instructions"
    )
    vulns = tester.get_vulnerabilities(target_id="agent-1")
    assert len(vulns) == 1
    assert vulns[0].category == AttackCategory.JAILBREAK


def test_record_probe_partial_success_creates_low_severity_vuln(tester):
    patterns = tester.get_patterns(category=AttackCategory.DATA_EXFILTRATION)
    pattern = patterns[0]
    tester.record_probe(
        pattern.pattern_id, "agent-1", ProbeResult.PARTIAL_SUCCESS,
        response="partial leak"
    )
    vulns = tester.get_vulnerabilities(target_id="agent-1")
    assert len(vulns) == 1
    assert vulns[0].severity == AttackSeverity.LOW


def test_no_vulnerability_on_blocked(tester):
    patterns = tester.get_patterns()
    tester.record_probe(patterns[0].pattern_id, "agent-1", ProbeResult.BLOCKED)
    vulns = tester.get_vulnerabilities(target_id="agent-1")
    assert len(vulns) == 0


def test_no_vulnerability_on_detected(tester):
    patterns = tester.get_patterns()
    tester.record_probe(patterns[0].pattern_id, "agent-1", ProbeResult.DETECTED)
    vulns = tester.get_vulnerabilities(target_id="agent-1")
    assert len(vulns) == 0


def test_get_probes_all(tester):
    patterns = tester.get_patterns()
    tester.record_probe(patterns[0].pattern_id, "a", ProbeResult.BLOCKED)
    tester.record_probe(patterns[1].pattern_id, "b", ProbeResult.DETECTED)
    probes = tester.get_probes()
    assert len(probes) == 2


def test_get_probes_by_target(tester):
    patterns = tester.get_patterns()
    tester.record_probe(patterns[0].pattern_id, "a", ProbeResult.BLOCKED)
    tester.record_probe(patterns[1].pattern_id, "b", ProbeResult.BLOCKED)
    probes = tester.get_probes(target_id="a")
    assert len(probes) == 1


def test_get_probes_by_result(tester):
    patterns = tester.get_patterns()
    tester.record_probe(patterns[0].pattern_id, "a", ProbeResult.BLOCKED)
    tester.record_probe(patterns[1].pattern_id, "a", ProbeResult.DETECTED)
    probes = tester.get_probes(result=ProbeResult.BLOCKED)
    assert len(probes) == 1


def test_get_vulnerabilities_by_category(tester):
    patterns = tester.get_patterns(category=AttackCategory.PROMPT_INJECTION)
    tester.record_probe(patterns[0].pattern_id, "a", ProbeResult.FULL_BYPASS)
    patterns_jb = tester.get_patterns(category=AttackCategory.JAILBREAK)
    tester.record_probe(patterns_jb[0].pattern_id, "a", ProbeResult.FULL_BYPASS)

    vulns = tester.get_vulnerabilities(category=AttackCategory.PROMPT_INJECTION)
    assert len(vulns) == 1


def test_get_vulnerabilities_by_severity(tester):
    patterns = tester.get_patterns(category=AttackCategory.JAILBREAK)
    tester.record_probe(patterns[0].pattern_id, "a", ProbeResult.FULL_BYPASS)
    tester.record_probe(patterns[0].pattern_id, "a", ProbeResult.PARTIAL_SUCCESS)

    critical = tester.get_vulnerabilities(severity=AttackSeverity.CRITICAL)
    low = tester.get_vulnerabilities(severity=AttackSeverity.LOW)
    assert len(critical) == 1
    assert len(low) == 1


def test_compute_robustness_all_blocked(tester):
    patterns = tester.get_patterns()
    for p in patterns[:5]:
        tester.record_probe(p.pattern_id, "agent-1", ProbeResult.BLOCKED)
    score = tester.compute_robustness("agent-1")
    assert score.overall_score == pytest.approx(1.0)
    assert score.blocked_count == 5
    assert score.bypassed_count == 0


def test_compute_robustness_all_bypassed(tester):
    patterns = tester.get_patterns()
    for p in patterns[:5]:
        tester.record_probe(p.pattern_id, "agent-1", ProbeResult.FULL_BYPASS)
    score = tester.compute_robustness("agent-1")
    assert score.overall_score == pytest.approx(0.0)
    assert score.bypassed_count == 5


def test_compute_robustness_mixed(tester):
    patterns = tester.get_patterns()
    tester.record_probe(patterns[0].pattern_id, "agent-1", ProbeResult.BLOCKED)
    tester.record_probe(patterns[1].pattern_id, "agent-1", ProbeResult.DETECTED)
    tester.record_probe(patterns[2].pattern_id, "agent-1", ProbeResult.FULL_BYPASS)
    score = tester.compute_robustness("agent-1")
    assert 0.0 < score.overall_score < 1.0
    assert score.total_probes == 3


def test_compute_robustness_empty(tester):
    score = tester.compute_robustness("unknown")
    assert score.overall_score == 0.0
    assert score.total_probes == 0


def test_compute_robustness_by_category(tester):
    pi_patterns = tester.get_patterns(category=AttackCategory.PROMPT_INJECTION)
    jb_patterns = tester.get_patterns(category=AttackCategory.JAILBREAK)
    tester.record_probe(pi_patterns[0].pattern_id, "a", ProbeResult.BLOCKED)
    tester.record_probe(jb_patterns[0].pattern_id, "a", ProbeResult.FULL_BYPASS)
    score = tester.compute_robustness("a")
    assert AttackCategory.PROMPT_INJECTION.value in score.by_category
    assert score.by_category[AttackCategory.PROMPT_INJECTION.value] == pytest.approx(1.0)
    assert score.by_category[AttackCategory.JAILBREAK.value] == pytest.approx(0.0)


def test_stats_empty():
    t = AdversarialTester()
    stats = t.get_stats()
    assert stats.total_patterns >= 9
    assert stats.total_probes == 0
    assert stats.total_vulnerabilities == 0


def test_stats_with_data(tester):
    patterns = tester.get_patterns()
    tester.record_probe(patterns[0].pattern_id, "a", ProbeResult.BLOCKED)
    tester.record_probe(patterns[1].pattern_id, "a", ProbeResult.FULL_BYPASS)
    stats = tester.get_stats()
    assert stats.total_probes == 2
    assert stats.total_vulnerabilities == 1
    assert stats.targets_tested == 1
    assert stats.avg_robustness > 0


def test_probe_latency_recorded(tester):
    patterns = tester.get_patterns()
    attempt = tester.record_probe(
        patterns[0].pattern_id, "a", ProbeResult.BLOCKED, latency_ms=42.5
    )
    assert attempt.latency_ms == 42.5


def test_probe_metadata_preserved(tester):
    patterns = tester.get_patterns()
    attempt = tester.record_probe(
        patterns[0].pattern_id, "a", ProbeResult.BLOCKED,
        metadata={"model": "gpt-4"}
    )
    assert attempt.metadata == {"model": "gpt-4"}
