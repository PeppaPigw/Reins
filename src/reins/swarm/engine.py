from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime

from reins.swarm.types import (
    ConsensusMethod,
    PheromoneTrail,
    SignalKind,
    SwarmAgent,
    SwarmDecision,
    SwarmRole,
    SwarmSignal,
    SwarmStats,
    SwarmTask,
)


class SwarmEngine:
    """Emergent multi-agent coordination through stigmergy and collective intelligence.

    Manages swarm agents with pheromone-based signaling, role assignment,
    collective decision-making, and task allocation through emergent behavior.
    """

    def __init__(self, decay_interval: float = 1.0) -> None:
        self._agents: dict[str, SwarmAgent] = {}
        self._signals: list[SwarmSignal] = []
        self._trails: dict[str, PheromoneTrail] = {}
        self._decisions: dict[str, SwarmDecision] = {}
        self._tasks: dict[str, SwarmTask] = {}
        self._decay_interval = decay_interval

    def register_agent(self, agent_id: str, role: SwarmRole = SwarmRole.IDLE,
                       position: tuple[float, ...] = (),
                       energy: float = 1.0) -> SwarmAgent:
        agent = SwarmAgent(agent_id=agent_id, role=role, position=position, energy=energy)
        self._agents[agent_id] = agent
        return agent

    def get_agent(self, agent_id: str) -> SwarmAgent | None:
        return self._agents.get(agent_id)

    def update_agent(self, agent_id: str, role: SwarmRole | None = None,
                     position: tuple[float, ...] | None = None,
                     energy: float | None = None) -> SwarmAgent | None:
        agent = self._agents.get(agent_id)
        if not agent:
            return None
        updates: dict = {}
        if role is not None:
            updates["role"] = role
        if position is not None:
            updates["position"] = position
        if energy is not None:
            updates["energy"] = energy
        if updates:
            agent = agent.model_copy(update=updates)
            self._agents[agent_id] = agent
        return agent

    def emit_signal(self, source_agent: str, kind: SignalKind,
                    target: str = "", intensity: float = 1.0,
                    payload: dict | None = None,
                    decay_rate: float = 0.1) -> SwarmSignal:
        signal = SwarmSignal(
            kind=kind,
            source_agent=source_agent,
            target=target,
            intensity=intensity,
            payload=payload or {},
            decay_rate=decay_rate,
        )
        self._signals.append(signal)
        return signal

    def get_signals(self, kind: SignalKind | None = None,
                    target: str | None = None,
                    min_intensity: float = 0.0) -> list[SwarmSignal]:
        signals = self._signals
        if kind:
            signals = [s for s in signals if s.kind == kind]
        if target:
            signals = [s for s in signals if s.target == target or s.target == ""]
        if min_intensity > 0:
            signals = [s for s in signals if s.intensity >= min_intensity]
        return signals

    def deposit_pheromone(self, agent_id: str, resource: str,
                         intensity: float = 1.0,
                         decay_rate: float = 0.05) -> PheromoneTrail:
        existing = self._trails.get(resource)
        if existing:
            new_intensity = min(existing.intensity + intensity, 10.0)
            trail = existing.model_copy(update={"intensity": new_intensity})
        else:
            trail = PheromoneTrail(
                resource=resource,
                deposited_by=agent_id,
                intensity=intensity,
                decay_rate=decay_rate,
            )
        self._trails[resource] = trail
        return trail

    def get_trail(self, resource: str) -> PheromoneTrail | None:
        return self._trails.get(resource)

    def get_strongest_trails(self, top_n: int = 5) -> list[PheromoneTrail]:
        trails = sorted(self._trails.values(), key=lambda t: t.intensity, reverse=True)
        return trails[:top_n]

    def decay_signals(self) -> int:
        remaining = []
        removed = 0
        for signal in self._signals:
            new_intensity = signal.intensity * (1.0 - signal.decay_rate)
            if new_intensity >= 0.01:
                remaining.append(signal.model_copy(update={"intensity": new_intensity}))
            else:
                removed += 1
        self._signals = remaining
        return removed

    def decay_trails(self) -> int:
        removed = 0
        updated: dict[str, PheromoneTrail] = {}
        for resource, trail in self._trails.items():
            new_intensity = trail.intensity * (1.0 - trail.decay_rate)
            if new_intensity >= 0.01:
                updated[resource] = trail.model_copy(update={"intensity": new_intensity})
            else:
                removed += 1
        self._trails = updated
        return removed

    def propose_decision(self, proposal: str,
                         method: ConsensusMethod = ConsensusMethod.MAJORITY_VOTE,
                         quorum: int = 1) -> SwarmDecision:
        decision = SwarmDecision(proposal=proposal, method=method, quorum=quorum)
        self._decisions[decision.decision_id] = decision
        return decision

    def vote(self, decision_id: str, in_favor: bool) -> SwarmDecision | None:
        decision = self._decisions.get(decision_id)
        if not decision or decision.resolved:
            return decision

        updates: dict = {}
        if in_favor:
            updates["votes_for"] = decision.votes_for + 1
        else:
            updates["votes_against"] = decision.votes_against + 1

        decision = decision.model_copy(update=updates)
        total_votes = decision.votes_for + decision.votes_against

        if total_votes >= decision.quorum:
            resolved, outcome = self._check_consensus(decision)
            if resolved:
                decision = decision.model_copy(update={
                    "resolved": True,
                    "outcome": outcome,
                    "decided_at": datetime.now(UTC),
                })

        self._decisions[decision.decision_id] = decision
        return decision

    def get_decision(self, decision_id: str) -> SwarmDecision | None:
        return self._decisions.get(decision_id)

    def create_task(self, description: str, required_agents: int = 1,
                    priority: float = 1.0) -> SwarmTask:
        task = SwarmTask(
            description=description,
            required_agents=required_agents,
            priority=priority,
        )
        self._tasks[task.task_id] = task
        return task

    def assign_task(self, task_id: str, agent_id: str) -> SwarmTask | None:
        task = self._tasks.get(task_id)
        if not task or task.completed:
            return task
        if agent_id in task.assigned_agents:
            return task
        new_assigned = task.assigned_agents + (agent_id,)
        task = task.model_copy(update={"assigned_agents": new_assigned})
        self._tasks[task_id] = task
        return task

    def complete_task(self, task_id: str) -> SwarmTask | None:
        task = self._tasks.get(task_id)
        if not task:
            return None
        task = task.model_copy(update={"completed": True})
        self._tasks[task_id] = task
        return task

    def get_unassigned_tasks(self) -> list[SwarmTask]:
        return [
            t for t in self._tasks.values()
            if not t.completed and len(t.assigned_agents) < t.required_agents
        ]

    def compute_distance(self, agent_a: str, agent_b: str) -> float | None:
        a = self._agents.get(agent_a)
        b = self._agents.get(agent_b)
        if not a or not b or not a.position or not b.position:
            return None
        if len(a.position) != len(b.position):
            return None
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(a.position, b.position)))

    def get_neighbors(self, agent_id: str, radius: float) -> list[SwarmAgent]:
        agent = self._agents.get(agent_id)
        if not agent or not agent.position:
            return []
        neighbors = []
        for other in self._agents.values():
            if other.agent_id == agent_id or not other.position:
                continue
            dist = self.compute_distance(agent_id, other.agent_id)
            if dist is not None and dist <= radius:
                neighbors.append(other)
        return neighbors

    def auto_assign_roles(self) -> dict[str, SwarmRole]:
        assignments: dict[str, SwarmRole] = {}
        agents = list(self._agents.values())
        if not agents:
            return assignments

        unassigned_tasks = self.get_unassigned_tasks()
        idle_agents = [a for a in agents if a.role == SwarmRole.IDLE]

        for agent in idle_agents[:1]:
            assignments[agent.agent_id] = SwarmRole.SCOUT
            self.update_agent(agent.agent_id, role=SwarmRole.SCOUT)

        worker_count = min(len(idle_agents) - 1, len(unassigned_tasks))
        for agent in idle_agents[1:1 + worker_count]:
            assignments[agent.agent_id] = SwarmRole.WORKER
            self.update_agent(agent.agent_id, role=SwarmRole.WORKER)

        return assignments

    def get_stats(self) -> SwarmStats:
        by_role: dict[str, int] = defaultdict(int)
        total_energy = 0.0
        for agent in self._agents.values():
            by_role[agent.role.value] += 1
            total_energy += agent.energy

        avg_energy = total_energy / len(self._agents) if self._agents else 0.0
        tasks_completed = sum(1 for t in self._tasks.values() if t.completed)

        return SwarmStats(
            total_agents=len(self._agents),
            active_signals=len(self._signals),
            active_trails=len(self._trails),
            decisions_made=sum(1 for d in self._decisions.values() if d.resolved),
            tasks_completed=tasks_completed,
            avg_energy=avg_energy,
            by_role=dict(by_role),
        )

    def _check_consensus(self, decision: SwarmDecision) -> tuple[bool, bool | None]:
        total = decision.votes_for + decision.votes_against
        if total < decision.quorum:
            return False, None

        if decision.method == ConsensusMethod.MAJORITY_VOTE:
            return True, decision.votes_for > decision.votes_against
        elif decision.method == ConsensusMethod.QUORUM_SENSING:
            return True, decision.votes_for >= decision.quorum
        elif decision.method == ConsensusMethod.WEIGHTED_VOTE:
            return True, decision.votes_for > decision.votes_against
        elif decision.method == ConsensusMethod.THRESHOLD:
            ratio = decision.votes_for / total if total > 0 else 0
            if ratio >= 0.75:
                return True, True
            elif (1 - ratio) >= 0.75:
                return True, False
            return False, None

        return True, decision.votes_for > decision.votes_against
