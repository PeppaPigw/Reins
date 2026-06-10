"""Tests for Kernel Health Monitor."""

from __future__ import annotations

import pytest

from reins.event_bus import EventBus
from reins.kernel.health import HealthStatus, KernelHealthMonitor


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def monitor(bus):
    return KernelHealthMonitor(bus)


def test_healthy_when_no_issues(monitor):
    status = monitor.assess(total_agents=5, quarantined_count=0,
                            total_evaluations=100, denied_count=5)
    assert status == HealthStatus.HEALTHY


def test_degraded_when_no_agents(monitor):
    status = monitor.assess(total_agents=0, quarantined_count=0,
                            total_evaluations=0, denied_count=0)
    assert status == HealthStatus.DEGRADED


def test_critical_when_many_quarantined(monitor):
    status = monitor.assess(total_agents=4, quarantined_count=3,
                            total_evaluations=10, denied_count=1)
    assert status == HealthStatus.CRITICAL


def test_degraded_when_high_denial_rate(monitor):
    status = monitor.assess(total_agents=5, quarantined_count=0,
                            total_evaluations=10, denied_count=9)
    assert status == HealthStatus.DEGRADED


def test_overall_status_reflects_worst(monitor):
    monitor.report("a", HealthStatus.HEALTHY)
    monitor.report("b", HealthStatus.CRITICAL, "bad")
    assert monitor.status == HealthStatus.CRITICAL


def test_health_events_emitted(bus, monitor):
    monitor.assess(total_agents=4, quarantined_count=3,
                   total_evaluations=10, denied_count=1)
    events = bus.replay("health.critical")
    assert len(events) == 1


def test_checks_dict(monitor):
    monitor.report("test", HealthStatus.HEALTHY)
    assert "test" in monitor.checks
