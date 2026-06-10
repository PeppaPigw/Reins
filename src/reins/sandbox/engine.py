from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from reins.sandbox.types import (
    CapabilityGrant,
    IsolationLevel,
    ResourceKind,
    ResourceLimit,
    ResourceUsage,
    SandboxConfig,
    SandboxState,
    SandboxStats,
    SandboxStatus,
    SandboxViolation,
    ViolationAction,
)


class SandboxManager:
    """Enforces resource limits, capability restrictions, and blast radius containment.

    Each agent runs in a sandbox with configurable resource limits, capability
    grants, and isolation levels. Violations trigger configurable actions from
    warnings to termination.
    """

    def __init__(self) -> None:
        self._configs: dict[str, SandboxConfig] = {}
        self._usage: dict[str, dict[ResourceKind, float]] = defaultdict(lambda: defaultdict(float))
        self._peak: dict[str, dict[ResourceKind, float]] = defaultdict(lambda: defaultdict(float))
        self._status: dict[str, SandboxStatus] = {}
        self._violations: dict[str, list[SandboxViolation]] = defaultdict(list)
        self._created_at: dict[str, datetime] = {}

    def create_sandbox(self, config: SandboxConfig) -> SandboxState:
        self._configs[config.sandbox_id] = config
        self._status[config.sandbox_id] = SandboxStatus.ACTIVE
        self._created_at[config.sandbox_id] = datetime.now(UTC)
        return self._build_state(config.sandbox_id)

    def get_state(self, sandbox_id: str) -> SandboxState | None:
        if sandbox_id not in self._configs:
            return None
        return self._build_state(sandbox_id)

    def consume_resource(self, sandbox_id: str, resource: ResourceKind,
                         amount: float) -> SandboxViolation | None:
        if sandbox_id not in self._configs:
            return None
        if self._status.get(sandbox_id) != SandboxStatus.ACTIVE:
            return SandboxViolation(
                sandbox_id=sandbox_id,
                resource=resource,
                message=f"Sandbox is {self._status.get(sandbox_id, 'unknown').value}",
                action_taken=ViolationAction.TERMINATE,
            )

        self._usage[sandbox_id][resource] += amount
        current = self._usage[sandbox_id][resource]
        self._peak[sandbox_id][resource] = max(self._peak[sandbox_id][resource], current)

        config = self._configs[sandbox_id]
        for limit in config.resource_limits:
            if limit.resource != resource:
                continue

            if current > limit.hard_limit:
                violation = SandboxViolation(
                    sandbox_id=sandbox_id,
                    resource=resource,
                    message=f"Hard limit breached: {current:.0f} > {limit.hard_limit:.0f}",
                    action_taken=limit.on_hard_breach,
                    value=current,
                    limit=limit.hard_limit,
                )
                self._violations[sandbox_id].append(violation)
                self._apply_action(sandbox_id, limit.on_hard_breach)
                return violation

            if current > limit.soft_limit:
                violation = SandboxViolation(
                    sandbox_id=sandbox_id,
                    resource=resource,
                    message=f"Soft limit breached: {current:.0f} > {limit.soft_limit:.0f}",
                    action_taken=limit.on_soft_breach,
                    value=current,
                    limit=limit.soft_limit,
                )
                self._violations[sandbox_id].append(violation)
                self._apply_action(sandbox_id, limit.on_soft_breach)
                return violation

        return None

    def check_capability(self, sandbox_id: str, capability: str) -> bool:
        config = self._configs.get(sandbox_id)
        if not config:
            return False
        if self._status.get(sandbox_id) != SandboxStatus.ACTIVE:
            return False

        for grant in config.capabilities:
            if grant.capability == capability:
                if grant.expires_at and grant.expires_at < datetime.now(UTC):
                    return False
                return grant.allowed
        return False

    def check_path_access(self, sandbox_id: str, path: str) -> bool:
        config = self._configs.get(sandbox_id)
        if not config:
            return False
        if not config.allow_filesystem:
            return False

        for blocked in config.blocked_paths:
            if path.startswith(blocked):
                return False

        if config.allowed_paths:
            return any(path.startswith(allowed) for allowed in config.allowed_paths)
        return True

    def suspend(self, sandbox_id: str) -> bool:
        if self._status.get(sandbox_id) == SandboxStatus.ACTIVE:
            self._status[sandbox_id] = SandboxStatus.SUSPENDED
            return True
        return False

    def resume(self, sandbox_id: str) -> bool:
        if self._status.get(sandbox_id) == SandboxStatus.SUSPENDED:
            self._status[sandbox_id] = SandboxStatus.ACTIVE
            return True
        return False

    def terminate(self, sandbox_id: str) -> bool:
        if sandbox_id in self._status and self._status[sandbox_id] != SandboxStatus.TERMINATED:
            self._status[sandbox_id] = SandboxStatus.TERMINATED
            return True
        return False

    def get_usage(self, sandbox_id: str) -> list[ResourceUsage]:
        config = self._configs.get(sandbox_id)
        if not config:
            return []

        usages = []
        for limit in config.resource_limits:
            current = self._usage[sandbox_id][limit.resource]
            peak = self._peak[sandbox_id][limit.resource]
            utilization = current / limit.hard_limit * 100 if limit.hard_limit > 0 else 0.0
            usages.append(ResourceUsage(
                resource=limit.resource,
                current=current,
                peak=peak,
                total=current,
                limit=limit,
                utilization_pct=utilization,
            ))
        return usages

    def get_violations(self, sandbox_id: str | None = None) -> list[SandboxViolation]:
        if sandbox_id:
            return list(self._violations.get(sandbox_id, []))
        all_violations = []
        for v_list in self._violations.values():
            all_violations.extend(v_list)
        return all_violations

    def get_stats(self) -> SandboxStats:
        if not self._configs:
            return SandboxStats()

        active = sum(1 for s in self._status.values() if s == SandboxStatus.ACTIVE)
        terminated = sum(1 for s in self._status.values() if s == SandboxStatus.TERMINATED)
        breached = sum(1 for s in self._status.values() if s == SandboxStatus.BREACHED)
        total_violations = sum(len(v) for v in self._violations.values())

        by_resource: dict[str, float] = defaultdict(float)
        for sandbox_usage in self._usage.values():
            for resource, amount in sandbox_usage.items():
                by_resource[resource.value] += amount

        return SandboxStats(
            total_sandboxes=len(self._configs),
            active=active,
            terminated=terminated,
            breached=breached,
            total_violations=total_violations,
            by_resource=dict(by_resource),
        )

    def _apply_action(self, sandbox_id: str, action: ViolationAction) -> None:
        if action == ViolationAction.SUSPEND:
            self._status[sandbox_id] = SandboxStatus.SUSPENDED
        elif action == ViolationAction.TERMINATE:
            self._status[sandbox_id] = SandboxStatus.TERMINATED
        elif action == ViolationAction.THROTTLE:
            pass

    def _build_state(self, sandbox_id: str) -> SandboxState:
        config = self._configs[sandbox_id]
        return SandboxState(
            sandbox_id=sandbox_id,
            agent_id=config.agent_id,
            status=self._status.get(sandbox_id, SandboxStatus.ACTIVE),
            usage=tuple(self.get_usage(sandbox_id)),
            violations=tuple(self._violations.get(sandbox_id, [])),
            created_at=self._created_at.get(sandbox_id, datetime.now(UTC)),
        )
