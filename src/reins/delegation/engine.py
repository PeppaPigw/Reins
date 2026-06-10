from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from reins.delegation.types import (
    AgentProfile,
    Capability,
    DelegationPolicy,
    DelegationRecord,
    DelegationStats,
    DelegationStatus,
    DelegationTask,
    EscalationReason,
)


class DelegationEngine:
    """Hierarchical task delegation with accountability chains and capability matching.

    Matches tasks to agents based on capabilities, manages delegation lifecycle,
    tracks accountability, and handles escalation when delegates fail.
    """

    def __init__(self, policy: DelegationPolicy = DelegationPolicy.FLEXIBLE) -> None:
        self._policy = policy
        self._agents: dict[str, AgentProfile] = {}
        self._records: list[DelegationRecord] = []
        self._task_records: dict[str, list[DelegationRecord]] = defaultdict(list)
        self._round_robin_idx: int = 0

    def register_agent(self, profile: AgentProfile) -> AgentProfile:
        self._agents[profile.agent_id] = profile
        return profile

    def get_agent(self, agent_id: str) -> AgentProfile | None:
        return self._agents.get(agent_id)

    def unregister_agent(self, agent_id: str) -> bool:
        if agent_id in self._agents:
            del self._agents[agent_id]
            return True
        return False

    def delegate(self, task: DelegationTask, delegator: str,
                 delegate: str | None = None) -> DelegationRecord | None:
        if delegate:
            agent = self._agents.get(delegate)
            if not agent or not agent.available:
                return None
            if not self._has_capacity(agent):
                return None
        else:
            agent = self._find_best_agent(task)
            if not agent:
                return None
            delegate = agent.agent_id

        record = DelegationRecord(
            task_id=task.task_id,
            delegator=delegator,
            delegate=delegate,
            status=DelegationStatus.ASSIGNED,
        )
        self._records.append(record)
        self._task_records[task.task_id].append(record)
        self._increment_load(delegate)
        return record

    def complete(self, record_id: str, result: dict | None = None) -> DelegationRecord | None:
        record = self._find_record(record_id)
        if not record:
            return None
        if record.status not in (DelegationStatus.ASSIGNED, DelegationStatus.IN_PROGRESS):
            return None

        updated = DelegationRecord(
            record_id=record.record_id,
            task_id=record.task_id,
            delegator=record.delegator,
            delegate=record.delegate,
            status=DelegationStatus.COMPLETED,
            attempt=record.attempt,
            result=result or {},
            assigned_at=record.assigned_at,
            completed_at=datetime.now(UTC),
        )
        self._replace_record(record_id, updated)
        self._decrement_load(record.delegate)
        return updated

    def fail(self, record_id: str, reason: EscalationReason | None = None) -> DelegationRecord | None:
        record = self._find_record(record_id)
        if not record:
            return None
        if record.status not in (DelegationStatus.ASSIGNED, DelegationStatus.IN_PROGRESS):
            return None

        updated = DelegationRecord(
            record_id=record.record_id,
            task_id=record.task_id,
            delegator=record.delegator,
            delegate=record.delegate,
            status=DelegationStatus.FAILED,
            attempt=record.attempt,
            escalation_reason=reason,
            assigned_at=record.assigned_at,
            completed_at=datetime.now(UTC),
        )
        self._replace_record(record_id, updated)
        self._decrement_load(record.delegate)
        return updated

    def escalate(self, record_id: str, reason: EscalationReason) -> DelegationRecord | None:
        record = self._find_record(record_id)
        if not record:
            return None

        updated = DelegationRecord(
            record_id=record.record_id,
            task_id=record.task_id,
            delegator=record.delegator,
            delegate=record.delegate,
            status=DelegationStatus.ESCALATED,
            attempt=record.attempt,
            escalation_reason=reason,
            assigned_at=record.assigned_at,
            completed_at=datetime.now(UTC),
        )
        self._replace_record(record_id, updated)
        self._decrement_load(record.delegate)
        return updated

    def revoke(self, record_id: str) -> bool:
        record = self._find_record(record_id)
        if not record:
            return False
        if record.status not in (DelegationStatus.ASSIGNED, DelegationStatus.IN_PROGRESS, DelegationStatus.PENDING):
            return False

        updated = DelegationRecord(
            record_id=record.record_id,
            task_id=record.task_id,
            delegator=record.delegator,
            delegate=record.delegate,
            status=DelegationStatus.REVOKED,
            attempt=record.attempt,
            assigned_at=record.assigned_at,
            completed_at=datetime.now(UTC),
        )
        self._replace_record(record_id, updated)
        self._decrement_load(record.delegate)
        return True

    def get_records(self, task_id: str | None = None, delegate: str | None = None,
                    status: DelegationStatus | None = None) -> list[DelegationRecord]:
        records = self._records
        if task_id:
            records = [r for r in records if r.task_id == task_id]
        if delegate:
            records = [r for r in records if r.delegate == delegate]
        if status:
            records = [r for r in records if r.status == status]
        return records

    def find_capable_agents(self, task: DelegationTask) -> list[AgentProfile]:
        capable = []
        for agent in self._agents.values():
            if not agent.available:
                continue
            if not self._has_capacity(agent):
                continue
            if self._matches_capabilities(agent, task):
                capable.append(agent)
        return capable

    def get_stats(self) -> DelegationStats:
        total = len(self._records)
        completed = sum(1 for r in self._records if r.status == DelegationStatus.COMPLETED)
        failed = sum(1 for r in self._records if r.status == DelegationStatus.FAILED)
        escalated = sum(1 for r in self._records if r.status == DelegationStatus.ESCALATED)

        attempts = [r.attempt for r in self._records]
        avg_attempts = sum(attempts) / len(attempts) if attempts else 0.0

        concluded = completed + failed + escalated
        success_rate = completed / concluded if concluded else 0.0

        by_status: dict[str, int] = defaultdict(int)
        for r in self._records:
            by_status[r.status.value] += 1

        return DelegationStats(
            total_delegations=total,
            completed=completed,
            failed=failed,
            escalated=escalated,
            avg_attempts=avg_attempts,
            success_rate=success_rate,
            agents_registered=len(self._agents),
            by_status=dict(by_status),
        )

    def _find_best_agent(self, task: DelegationTask) -> AgentProfile | None:
        candidates = self.find_capable_agents(task)
        if not candidates:
            available = [a for a in self._agents.values() if a.available and self._has_capacity(a)]
            if not available:
                return None
            candidates = available

        if self._policy == DelegationPolicy.ROUND_ROBIN:
            idx = self._round_robin_idx % len(candidates)
            self._round_robin_idx += 1
            return candidates[idx]

        return max(candidates, key=lambda a: a.trust_score)

    def _matches_capabilities(self, agent: AgentProfile, task: DelegationTask) -> bool:
        if not task.required_capabilities:
            return True
        agent_caps = {c.name: c.level for c in agent.capabilities}
        for req in task.required_capabilities:
            if req.name not in agent_caps:
                return False
            if agent_caps[req.name] < req.level:
                return False
        return True

    def _has_capacity(self, agent: AgentProfile) -> bool:
        return agent.current_load < agent.max_concurrent

    def _increment_load(self, agent_id: str) -> None:
        agent = self._agents.get(agent_id)
        if agent:
            self._agents[agent_id] = AgentProfile(
                agent_id=agent.agent_id,
                capabilities=agent.capabilities,
                max_concurrent=agent.max_concurrent,
                current_load=agent.current_load + 1,
                trust_score=agent.trust_score,
                available=agent.available,
            )

    def _decrement_load(self, agent_id: str) -> None:
        agent = self._agents.get(agent_id)
        if agent:
            self._agents[agent_id] = AgentProfile(
                agent_id=agent.agent_id,
                capabilities=agent.capabilities,
                max_concurrent=agent.max_concurrent,
                current_load=max(0, agent.current_load - 1),
                trust_score=agent.trust_score,
                available=agent.available,
            )

    def _find_record(self, record_id: str) -> DelegationRecord | None:
        for r in self._records:
            if r.record_id == record_id:
                return r
        return None

    def _replace_record(self, record_id: str, updated: DelegationRecord) -> None:
        for i, r in enumerate(self._records):
            if r.record_id == record_id:
                self._records[i] = updated
                break
        task_records = self._task_records.get(updated.task_id, [])
        for i, r in enumerate(task_records):
            if r.record_id == record_id:
                task_records[i] = updated
                break
