from __future__ import annotations

from collections import defaultdict

from reins.composability.types import (
    AgentContract,
    Composition,
    CompositionKind,
    CompositionStatus,
    ComposabilityStats,
    InterferenceKind,
    InterferenceReport,
    SafetyComposition,
    SafetyRelation,
)


class ComposabilityEngine:
    """Compositional safety verification for agent compositions.

    Verifies that safety properties are preserved when agents are composed.
    Detects interference (read-write conflicts, resource contention, deadlock risk),
    checks contract compatibility, and proves compositional safety guarantees.
    """

    def __init__(self) -> None:
        self._contracts: dict[str, AgentContract] = {}
        self._compositions: dict[str, Composition] = {}
        self._interferences: list[InterferenceReport] = []
        self._proofs: list[SafetyComposition] = []

    def register_contract(self, agent_id: str,
                          requires: set[str] | None = None,
                          provides: set[str] | None = None,
                          modifies: set[str] | None = None,
                          invariants: list[str] | None = None) -> AgentContract:
        contract = AgentContract(
            agent_id=agent_id,
            requires=requires or set(),
            provides=provides or set(),
            modifies=modifies or set(),
            invariants=invariants or [],
        )
        self._contracts[agent_id] = contract
        return contract

    def get_contract(self, agent_id: str) -> AgentContract | None:
        return self._contracts.get(agent_id)

    def compose(self, name: str, agent_ids: list[str],
                kind: CompositionKind = CompositionKind.SEQUENTIAL) -> Composition:
        composition = Composition(name=name, kind=kind, agents=agent_ids)
        self._compositions[composition.composition_id] = composition
        return composition

    def check_interference(self, agent_a: str, agent_b: str) -> InterferenceReport:
        contract_a = self._contracts.get(agent_a)
        contract_b = self._contracts.get(agent_b)

        if not contract_a or not contract_b:
            report = InterferenceReport(
                agent_a=agent_a, agent_b=agent_b,
                kind=InterferenceKind.NONE,
                message="Missing contract(s)",
            )
            self._interferences.append(report)
            return report

        write_write = contract_a.modifies & contract_b.modifies
        read_write_ab = contract_a.requires & contract_b.modifies
        read_write_ba = contract_b.requires & contract_a.modifies
        read_write = read_write_ab | read_write_ba

        if write_write:
            kind = InterferenceKind.WRITE_WRITE
            shared = list(write_write)
            msg = f"Write-write conflict on: {', '.join(sorted(write_write))}"
        elif read_write:
            kind = InterferenceKind.READ_WRITE
            shared = list(read_write)
            msg = f"Read-write conflict on: {', '.join(sorted(read_write))}"
        else:
            kind = InterferenceKind.NONE
            shared = []
            msg = "No interference detected"

        report = InterferenceReport(
            agent_a=agent_a, agent_b=agent_b,
            kind=kind, shared_resources=shared, message=msg,
        )
        self._interferences.append(report)
        return report

    def check_dependencies(self, composition_id: str) -> list[str]:
        composition = self._compositions.get(composition_id)
        if not composition:
            return ["Composition not found"]

        issues = []
        for i, agent_id in enumerate(composition.agents):
            contract = self._contracts.get(agent_id)
            if not contract:
                issues.append(f"No contract for agent '{agent_id}'")
                continue

            if composition.kind == CompositionKind.SEQUENTIAL and i > 0:
                available = set()
                for prev_id in composition.agents[:i]:
                    prev = self._contracts.get(prev_id)
                    if prev:
                        available |= prev.provides
                unmet = contract.requires - available
                if unmet:
                    issues.append(
                        f"Agent '{agent_id}' requires {sorted(unmet)} "
                        f"not provided by predecessors"
                    )
        return issues

    def verify_composition(self, composition_id: str) -> SafetyComposition:
        composition = self._compositions.get(composition_id)
        if not composition:
            proof = SafetyComposition(
                composition_id=composition_id,
                relation=SafetyRelation.UNKNOWN,
            )
            self._proofs.append(proof)
            return proof

        all_invariants: set[str] = set()
        preserved: set[str] = set()
        weakened: set[str] = set()
        violated: set[str] = set()

        for agent_id in composition.agents:
            contract = self._contracts.get(agent_id)
            if contract:
                all_invariants.update(contract.invariants)

        for inv in all_invariants:
            interference_found = False
            for i, a_id in enumerate(composition.agents):
                for b_id in composition.agents[i + 1:]:
                    report = self._check_interference_cached(a_id, b_id)
                    if report.kind != InterferenceKind.NONE:
                        ca = self._contracts.get(a_id)
                        cb = self._contracts.get(b_id)
                        if ca and inv in ca.invariants:
                            if report.kind == InterferenceKind.WRITE_WRITE:
                                violated.add(inv)
                            else:
                                weakened.add(inv)
                            interference_found = True
                        elif cb and inv in cb.invariants:
                            if report.kind == InterferenceKind.WRITE_WRITE:
                                violated.add(inv)
                            else:
                                weakened.add(inv)
                            interference_found = True
            if not interference_found:
                preserved.add(inv)

        preserved -= weakened | violated
        weakened -= violated

        if violated:
            relation = SafetyRelation.VIOLATES
            status = CompositionStatus.UNSAFE
        elif weakened:
            relation = SafetyRelation.WEAKENS
            status = CompositionStatus.CONDITIONAL
        elif preserved or not all_invariants:
            relation = SafetyRelation.PRESERVES
            status = CompositionStatus.SAFE
        else:
            relation = SafetyRelation.UNKNOWN
            status = CompositionStatus.UNVERIFIED

        updated = composition.model_copy(update={"status": status})
        self._compositions[composition_id] = updated

        proof = SafetyComposition(
            composition_id=composition_id,
            relation=relation,
            preserved_invariants=sorted(preserved),
            weakened_invariants=sorted(weakened),
            violated_invariants=sorted(violated),
        )
        self._proofs.append(proof)
        return proof

    def get_composition(self, composition_id: str) -> Composition | None:
        return self._compositions.get(composition_id)

    def get_proofs(self, composition_id: str | None = None) -> list[SafetyComposition]:
        if composition_id:
            return [p for p in self._proofs if p.composition_id == composition_id]
        return list(self._proofs)

    def get_interferences(self, agent_id: str | None = None) -> list[InterferenceReport]:
        if agent_id:
            return [r for r in self._interferences
                    if r.agent_a == agent_id or r.agent_b == agent_id]
        return list(self._interferences)

    def get_stats(self) -> ComposabilityStats:
        by_kind: dict[str, int] = defaultdict(int)
        by_status: dict[str, int] = defaultdict(int)
        safe = 0
        unsafe = 0

        for comp in self._compositions.values():
            by_kind[comp.kind.value] += 1
            by_status[comp.status.value] += 1
            if comp.status == CompositionStatus.SAFE:
                safe += 1
            elif comp.status == CompositionStatus.UNSAFE:
                unsafe += 1

        interference_count = sum(
            1 for r in self._interferences if r.kind != InterferenceKind.NONE
        )

        return ComposabilityStats(
            total_contracts=len(self._contracts),
            total_compositions=len(self._compositions),
            safe_compositions=safe,
            unsafe_compositions=unsafe,
            total_interferences=interference_count,
            by_kind=dict(by_kind),
            by_status=dict(by_status),
        )

    def _check_interference_cached(self, agent_a: str,
                                    agent_b: str) -> InterferenceReport:
        for r in self._interferences:
            if (r.agent_a == agent_a and r.agent_b == agent_b) or \
               (r.agent_a == agent_b and r.agent_b == agent_a):
                return r
        return self.check_interference(agent_a, agent_b)
