"""Tests for agent sandboxing & resource isolation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from reins.sandbox import (
    CapabilityGrant,
    IsolationLevel,
    ResourceKind,
    ResourceLimit,
    ResourceUsage,
    SandboxConfig,
    SandboxManager,
    SandboxState,
    SandboxStats,
    SandboxStatus,
    SandboxViolation,
    ViolationAction,
)


@pytest.fixture
def manager() -> SandboxManager:
    return SandboxManager()


def _config(agent_id="agent-1", sandbox_id="sb-1", limits=(), capabilities=(),
            allowed_paths=(), blocked_paths=(), allow_filesystem=True):
    return SandboxConfig(
        sandbox_id=sandbox_id,
        agent_id=agent_id,
        resource_limits=limits,
        capabilities=capabilities,
        allowed_paths=allowed_paths,
        blocked_paths=blocked_paths,
        allow_filesystem=allow_filesystem,
    )


def _limit(resource=ResourceKind.API_CALLS, soft=80, hard=100,
           on_soft=ViolationAction.WARN, on_hard=ViolationAction.TERMINATE):
    return ResourceLimit(
        resource=resource,
        soft_limit=soft,
        hard_limit=hard,
        on_soft_breach=on_soft,
        on_hard_breach=on_hard,
    )


def test_create_sandbox(manager):
    config = _config()
    state = manager.create_sandbox(config)
    assert state.sandbox_id == "sb-1"
    assert state.status == SandboxStatus.ACTIVE


def test_get_state(manager):
    manager.create_sandbox(_config())
    state = manager.get_state("sb-1")
    assert state is not None
    assert state.agent_id == "agent-1"


def test_get_state_nonexistent(manager):
    assert manager.get_state("nonexistent") is None


def test_consume_resource_within_limits(manager):
    config = _config(limits=(_limit(soft=80, hard=100),))
    manager.create_sandbox(config)
    violation = manager.consume_resource("sb-1", ResourceKind.API_CALLS, 50)
    assert violation is None


def test_consume_resource_soft_breach(manager):
    config = _config(limits=(_limit(soft=80, hard=100),))
    manager.create_sandbox(config)
    violation = manager.consume_resource("sb-1", ResourceKind.API_CALLS, 85)
    assert violation is not None
    assert violation.action_taken == ViolationAction.WARN


def test_consume_resource_hard_breach(manager):
    config = _config(limits=(_limit(soft=80, hard=100),))
    manager.create_sandbox(config)
    violation = manager.consume_resource("sb-1", ResourceKind.API_CALLS, 101)
    assert violation is not None
    assert violation.action_taken == ViolationAction.TERMINATE

    state = manager.get_state("sb-1")
    assert state.status == SandboxStatus.TERMINATED


def test_consume_resource_accumulates(manager):
    config = _config(limits=(_limit(soft=80, hard=100),))
    manager.create_sandbox(config)
    manager.consume_resource("sb-1", ResourceKind.API_CALLS, 40)
    manager.consume_resource("sb-1", ResourceKind.API_CALLS, 30)
    violation = manager.consume_resource("sb-1", ResourceKind.API_CALLS, 15)
    assert violation is not None  # 85 > soft limit 80


def test_consume_resource_on_terminated_sandbox(manager):
    config = _config(limits=(_limit(soft=80, hard=100),))
    manager.create_sandbox(config)
    manager.consume_resource("sb-1", ResourceKind.API_CALLS, 101)

    violation = manager.consume_resource("sb-1", ResourceKind.API_CALLS, 1)
    assert violation is not None
    assert "Sandbox is terminated" in violation.message


def test_consume_resource_nonexistent_sandbox(manager):
    assert manager.consume_resource("nonexistent", ResourceKind.API_CALLS, 1) is None


def test_check_capability_granted(manager):
    cap = CapabilityGrant(capability="file_write", allowed=True)
    config = _config(capabilities=(cap,))
    manager.create_sandbox(config)
    assert manager.check_capability("sb-1", "file_write")


def test_check_capability_denied(manager):
    cap = CapabilityGrant(capability="file_write", allowed=False)
    config = _config(capabilities=(cap,))
    manager.create_sandbox(config)
    assert not manager.check_capability("sb-1", "file_write")


def test_check_capability_not_listed(manager):
    config = _config(capabilities=())
    manager.create_sandbox(config)
    assert not manager.check_capability("sb-1", "network_access")


def test_check_capability_expired(manager):
    cap = CapabilityGrant(
        capability="temp_access",
        allowed=True,
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    config = _config(capabilities=(cap,))
    manager.create_sandbox(config)
    assert not manager.check_capability("sb-1", "temp_access")


def test_check_capability_on_suspended(manager):
    cap = CapabilityGrant(capability="file_write", allowed=True)
    config = _config(capabilities=(cap,))
    manager.create_sandbox(config)
    manager.suspend("sb-1")
    assert not manager.check_capability("sb-1", "file_write")


def test_check_path_access_allowed(manager):
    config = _config(allowed_paths=("/workspace/", "/tmp/"))
    manager.create_sandbox(config)
    assert manager.check_path_access("sb-1", "/workspace/src/main.py")
    assert not manager.check_path_access("sb-1", "/etc/passwd")


def test_check_path_access_blocked(manager):
    config = _config(blocked_paths=("/secrets/", "/credentials/"))
    manager.create_sandbox(config)
    assert not manager.check_path_access("sb-1", "/secrets/api_key.txt")
    assert manager.check_path_access("sb-1", "/workspace/code.py")


def test_check_path_access_filesystem_disabled(manager):
    config = _config(allow_filesystem=False)
    manager.create_sandbox(config)
    assert not manager.check_path_access("sb-1", "/any/path")


def test_suspend_and_resume(manager):
    manager.create_sandbox(_config())
    assert manager.suspend("sb-1")
    state = manager.get_state("sb-1")
    assert state.status == SandboxStatus.SUSPENDED

    assert manager.resume("sb-1")
    state = manager.get_state("sb-1")
    assert state.status == SandboxStatus.ACTIVE


def test_suspend_already_suspended(manager):
    manager.create_sandbox(_config())
    manager.suspend("sb-1")
    assert not manager.suspend("sb-1")


def test_resume_not_suspended(manager):
    manager.create_sandbox(_config())
    assert not manager.resume("sb-1")


def test_terminate(manager):
    manager.create_sandbox(_config())
    assert manager.terminate("sb-1")
    state = manager.get_state("sb-1")
    assert state.status == SandboxStatus.TERMINATED


def test_terminate_already_terminated(manager):
    manager.create_sandbox(_config())
    manager.terminate("sb-1")
    assert not manager.terminate("sb-1")


def test_get_usage(manager):
    config = _config(limits=(_limit(resource=ResourceKind.API_CALLS, soft=80, hard=100),))
    manager.create_sandbox(config)
    manager.consume_resource("sb-1", ResourceKind.API_CALLS, 50)

    usages = manager.get_usage("sb-1")
    assert len(usages) == 1
    assert usages[0].current == 50
    assert usages[0].utilization_pct == 50.0


def test_get_usage_tracks_peak(manager):
    config = _config(limits=(_limit(resource=ResourceKind.MEMORY_BYTES, soft=800, hard=1000),))
    manager.create_sandbox(config)
    manager.consume_resource("sb-1", ResourceKind.MEMORY_BYTES, 500)
    manager.consume_resource("sb-1", ResourceKind.MEMORY_BYTES, 200)

    usages = manager.get_usage("sb-1")
    assert usages[0].peak == 700
    assert usages[0].current == 700


def test_get_violations(manager):
    config = _config(limits=(_limit(soft=80, hard=100),))
    manager.create_sandbox(config)
    manager.consume_resource("sb-1", ResourceKind.API_CALLS, 85)

    violations = manager.get_violations("sb-1")
    assert len(violations) == 1


def test_get_violations_all(manager):
    config1 = _config(sandbox_id="sb-1", limits=(_limit(soft=80, hard=100),))
    config2 = _config(sandbox_id="sb-2", agent_id="agent-2", limits=(_limit(soft=80, hard=100),))
    manager.create_sandbox(config1)
    manager.create_sandbox(config2)
    manager.consume_resource("sb-1", ResourceKind.API_CALLS, 85)
    manager.consume_resource("sb-2", ResourceKind.API_CALLS, 90)

    all_violations = manager.get_violations()
    assert len(all_violations) == 2


def test_soft_breach_suspend_action(manager):
    limit = _limit(soft=80, hard=100, on_soft=ViolationAction.SUSPEND)
    config = _config(limits=(limit,))
    manager.create_sandbox(config)
    manager.consume_resource("sb-1", ResourceKind.API_CALLS, 85)

    state = manager.get_state("sb-1")
    assert state.status == SandboxStatus.SUSPENDED


def test_stats_empty(manager):
    stats = manager.get_stats()
    assert stats.total_sandboxes == 0


def test_stats_with_data(manager):
    config1 = _config(sandbox_id="sb-1", limits=(_limit(soft=80, hard=100),))
    config2 = _config(sandbox_id="sb-2", agent_id="agent-2")
    manager.create_sandbox(config1)
    manager.create_sandbox(config2)
    manager.consume_resource("sb-1", ResourceKind.API_CALLS, 85)
    manager.terminate("sb-2")

    stats = manager.get_stats()
    assert stats.total_sandboxes == 2
    assert stats.active == 1
    assert stats.terminated == 1
    assert stats.total_violations == 1
    assert stats.by_resource["api_calls"] == 85.0


def test_multiple_resource_limits(manager):
    limits = (
        _limit(resource=ResourceKind.API_CALLS, soft=80, hard=100),
        _limit(resource=ResourceKind.TOKEN_COUNT, soft=5000, hard=10000),
    )
    config = _config(limits=limits)
    manager.create_sandbox(config)

    manager.consume_resource("sb-1", ResourceKind.API_CALLS, 50)
    manager.consume_resource("sb-1", ResourceKind.TOKEN_COUNT, 3000)

    usages = manager.get_usage("sb-1")
    assert len(usages) == 2
