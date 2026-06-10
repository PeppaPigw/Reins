"""Tests for resource accounting engine."""

from __future__ import annotations

import pytest

from reins.resource_accounting import (
    AllocationResult,
    QuotaStatus,
    ResourceAccountant,
    ResourceKind,
    ResourceQuota,
    ResourceRequest,
)


@pytest.fixture
def accountant() -> ResourceAccountant:
    return ResourceAccountant()


def test_set_quota(accountant):
    quota = accountant.set_quota("agent-1", ResourceKind.TOKENS, limit=10000)
    assert quota.agent_id == "agent-1"
    assert quota.limit == 10000
    assert quota.used == 0.0


def test_get_quota(accountant):
    accountant.set_quota("a", ResourceKind.API_CALLS, limit=100)
    assert accountant.get_quota("a", ResourceKind.API_CALLS) is not None
    assert accountant.get_quota("a", ResourceKind.TOKENS) is None


def test_allocate_granted(accountant):
    accountant.set_quota("a", ResourceKind.TOKENS, limit=1000)
    req = accountant.allocate("a", ResourceKind.TOKENS, 500)
    assert req.result == AllocationResult.GRANTED
    quota = accountant.get_quota("a", ResourceKind.TOKENS)
    assert quota.used == 500


def test_allocate_denied(accountant):
    accountant.set_quota("a", ResourceKind.TOKENS, limit=100)
    accountant.allocate("a", ResourceKind.TOKENS, 100)
    req = accountant.allocate("a", ResourceKind.TOKENS, 50)
    assert req.result == AllocationResult.DENIED


def test_allocate_throttled(accountant):
    accountant.set_quota("a", ResourceKind.API_CALLS, limit=10)
    accountant.allocate("a", ResourceKind.API_CALLS, 8)
    req = accountant.allocate("a", ResourceKind.API_CALLS, 5)
    assert req.result == AllocationResult.THROTTLED
    quota = accountant.get_quota("a", ResourceKind.API_CALLS)
    assert quota.used == quota.limit


def test_allocate_no_quota(accountant):
    req = accountant.allocate("unknown", ResourceKind.TOKENS, 999)
    assert req.result == AllocationResult.GRANTED


def test_get_status_available(accountant):
    accountant.set_quota("a", ResourceKind.TOKENS, limit=1000)
    assert accountant.get_status("a", ResourceKind.TOKENS) == QuotaStatus.AVAILABLE


def test_get_status_warning(accountant):
    accountant.set_quota("a", ResourceKind.TOKENS, limit=100, warning_threshold=0.8)
    accountant.allocate("a", ResourceKind.TOKENS, 85)
    assert accountant.get_status("a", ResourceKind.TOKENS) == QuotaStatus.WARNING


def test_get_status_exhausted(accountant):
    accountant.set_quota("a", ResourceKind.TOKENS, limit=100)
    accountant.allocate("a", ResourceKind.TOKENS, 100)
    assert accountant.get_status("a", ResourceKind.TOKENS) == QuotaStatus.EXHAUSTED


def test_get_status_no_quota(accountant):
    assert accountant.get_status("x", ResourceKind.TOKENS) == QuotaStatus.AVAILABLE


def test_release(accountant):
    accountant.set_quota("a", ResourceKind.MEMORY_MB, limit=1024)
    accountant.allocate("a", ResourceKind.MEMORY_MB, 512)
    assert accountant.release("a", ResourceKind.MEMORY_MB, 256) is True
    quota = accountant.get_quota("a", ResourceKind.MEMORY_MB)
    assert quota.used == 256


def test_release_no_quota(accountant):
    assert accountant.release("x", ResourceKind.TOKENS, 100) is False


def test_release_floor_zero(accountant):
    accountant.set_quota("a", ResourceKind.TOKENS, limit=100)
    accountant.allocate("a", ResourceKind.TOKENS, 50)
    accountant.release("a", ResourceKind.TOKENS, 999)
    quota = accountant.get_quota("a", ResourceKind.TOKENS)
    assert quota.used == 0.0


def test_reset_quota(accountant):
    accountant.set_quota("a", ResourceKind.TOKENS, limit=1000)
    accountant.allocate("a", ResourceKind.TOKENS, 800)
    assert accountant.reset_quota("a", ResourceKind.TOKENS) is True
    quota = accountant.get_quota("a", ResourceKind.TOKENS)
    assert quota.used == 0.0


def test_reset_nonexistent(accountant):
    assert accountant.reset_quota("x", ResourceKind.TOKENS) is False


def test_preempt(accountant):
    accountant.set_quota("a", ResourceKind.TOKENS, limit=1000)
    accountant.set_quota("a", ResourceKind.API_CALLS, limit=50)
    accountant.allocate("a", ResourceKind.TOKENS, 500)
    accountant.allocate("a", ResourceKind.API_CALLS, 20)
    preempted = accountant.preempt("a")
    assert len(preempted) == 2
    assert accountant.get_status("a", ResourceKind.TOKENS) == QuotaStatus.EXHAUSTED


def test_get_agent_usage(accountant):
    accountant.set_quota("a", ResourceKind.TOKENS, limit=1000)
    accountant.set_quota("a", ResourceKind.FILE_OPS, limit=50)
    accountant.allocate("a", ResourceKind.TOKENS, 300)
    accountant.allocate("a", ResourceKind.FILE_OPS, 10)
    usage = accountant.get_agent_usage("a")
    assert usage["tokens"] == 300
    assert usage["file_ops"] == 10


def test_stats_empty(accountant):
    stats = accountant.get_stats()
    assert stats.total_quotas == 0
    assert stats.total_requests == 0


def test_stats_populated(accountant):
    accountant.set_quota("a", ResourceKind.TOKENS, limit=100)
    accountant.set_quota("b", ResourceKind.TOKENS, limit=200)
    accountant.allocate("a", ResourceKind.TOKENS, 50)
    accountant.allocate("b", ResourceKind.TOKENS, 200)
    accountant.allocate("b", ResourceKind.TOKENS, 10)
    stats = accountant.get_stats()
    assert stats.total_quotas == 2
    assert stats.total_requests == 3
    assert stats.granted == 2
    assert stats.denied == 1
    assert stats.by_resource["tokens"] == 250
    assert stats.by_agent["a"] == 50


def test_all_resource_kinds(accountant):
    for kind in ResourceKind:
        accountant.set_quota("agent", kind, limit=100)
        accountant.allocate("agent", kind, 50)
    usage = accountant.get_agent_usage("agent")
    assert len(usage) == len(ResourceKind)
