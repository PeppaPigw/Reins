from __future__ import annotations

from collections import defaultdict

from reins.resource_accounting.types import (
    AllocationResult,
    QuotaStatus,
    ResourceAccountingStats,
    ResourceKind,
    ResourceQuota,
    ResourceRequest,
)


class ResourceAccountant:
    """Hard resource caps with preemption for agent execution.

    Tracks and enforces resource quotas (tokens, API calls, file ops,
    wall time, memory, network) per agent. Supports allocation requests,
    quota warnings, exhaustion detection, and preemption signals.
    """

    def __init__(self) -> None:
        self._quotas: dict[str, ResourceQuota] = {}
        self._requests: list[ResourceRequest] = []

    def set_quota(self, agent_id: str, resource: ResourceKind,
                  limit: float, warning_threshold: float = 0.8) -> ResourceQuota:
        quota = ResourceQuota(
            agent_id=agent_id,
            resource=resource,
            limit=limit,
            warning_threshold=warning_threshold,
        )
        key = f"{agent_id}:{resource.value}"
        self._quotas[key] = quota
        return quota

    def get_quota(self, agent_id: str, resource: ResourceKind) -> ResourceQuota | None:
        key = f"{agent_id}:{resource.value}"
        return self._quotas.get(key)

    def get_status(self, agent_id: str, resource: ResourceKind) -> QuotaStatus:
        quota = self.get_quota(agent_id, resource)
        if not quota:
            return QuotaStatus.AVAILABLE
        ratio = quota.used / quota.limit if quota.limit > 0 else 0
        if ratio >= 1.0:
            return QuotaStatus.EXHAUSTED
        if ratio >= quota.warning_threshold:
            return QuotaStatus.WARNING
        return QuotaStatus.AVAILABLE

    def allocate(self, agent_id: str, resource: ResourceKind,
                 amount: float) -> ResourceRequest:
        key = f"{agent_id}:{resource.value}"
        quota = self._quotas.get(key)

        if not quota:
            request = ResourceRequest(
                agent_id=agent_id, resource=resource,
                amount=amount, result=AllocationResult.GRANTED,
            )
            self._requests.append(request)
            return request

        remaining = quota.limit - quota.used
        if amount <= remaining:
            updated = quota.model_copy(update={"used": quota.used + amount})
            self._quotas[key] = updated
            result = AllocationResult.GRANTED
        elif remaining > 0:
            updated = quota.model_copy(update={"used": quota.limit})
            self._quotas[key] = updated
            result = AllocationResult.THROTTLED
        else:
            result = AllocationResult.DENIED

        request = ResourceRequest(
            agent_id=agent_id, resource=resource,
            amount=amount, result=result,
        )
        self._requests.append(request)
        return request

    def release(self, agent_id: str, resource: ResourceKind,
                amount: float) -> bool:
        key = f"{agent_id}:{resource.value}"
        quota = self._quotas.get(key)
        if not quota:
            return False
        new_used = max(0.0, quota.used - amount)
        self._quotas[key] = quota.model_copy(update={"used": new_used})
        return True

    def reset_quota(self, agent_id: str, resource: ResourceKind) -> bool:
        key = f"{agent_id}:{resource.value}"
        quota = self._quotas.get(key)
        if not quota:
            return False
        self._quotas[key] = quota.model_copy(update={"used": 0.0})
        return True

    def preempt(self, agent_id: str) -> list[ResourceQuota]:
        preempted = []
        for key, quota in self._quotas.items():
            if quota.agent_id == agent_id and quota.used > 0:
                self._quotas[key] = quota.model_copy(update={"used": quota.limit})
                preempted.append(self._quotas[key])
        return preempted

    def get_agent_usage(self, agent_id: str) -> dict[str, float]:
        usage: dict[str, float] = {}
        for key, quota in self._quotas.items():
            if quota.agent_id == agent_id:
                usage[quota.resource.value] = quota.used
        return usage

    def get_stats(self) -> ResourceAccountingStats:
        granted = sum(1 for r in self._requests if r.result == AllocationResult.GRANTED)
        denied = sum(1 for r in self._requests if r.result == AllocationResult.DENIED)
        throttled = sum(1 for r in self._requests if r.result == AllocationResult.THROTTLED)

        by_resource: dict[str, float] = defaultdict(float)
        by_agent: dict[str, float] = defaultdict(float)
        for quota in self._quotas.values():
            by_resource[quota.resource.value] += quota.used
            by_agent[quota.agent_id] += quota.used

        return ResourceAccountingStats(
            total_quotas=len(self._quotas),
            total_requests=len(self._requests),
            granted=granted,
            denied=denied,
            throttled=throttled,
            by_resource=dict(by_resource),
            by_agent=dict(by_agent),
        )
