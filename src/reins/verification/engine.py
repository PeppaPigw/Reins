from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Callable, Awaitable

from reins.verification.types import (
    DeadlockReport,
    Invariant,
    InvariantKind,
    PolicyCompletenessReport,
    StateTransition,
    VerificationReport,
    VerificationResult,
    VerificationStatus,
)


PredicateFunc = Callable[[dict[str, Any]], Awaitable[bool]]


class VerificationEngine:
    """Formal verification engine for agent behavior guarantees.

    Provides:
    - State invariant checking across event histories
    - Transition invariant verification
    - Safety property verification (bad states unreachable)
    - Liveness property verification (good states eventually reached)
    - Policy completeness proofs
    - Deadlock detection in state machines
    """

    def __init__(self) -> None:
        self._invariants: dict[str, Invariant] = {}
        self._predicates: dict[str, PredicateFunc] = {}
        self._transitions: list[StateTransition] = []
        self._states: set[str] = set()
        self._adjacency: dict[str, list[str]] = defaultdict(list)

    def register_invariant(
        self, invariant: Invariant, predicate: PredicateFunc
    ) -> None:
        self._invariants[invariant.invariant_id] = invariant
        self._predicates[invariant.invariant_id] = predicate

    def register_transition(self, transition: StateTransition) -> None:
        self._transitions.append(transition)
        self._states.add(transition.from_state)
        self._states.add(transition.to_state)
        self._adjacency[transition.from_state].append(transition.to_state)

    def register_states(self, states: list[str]) -> None:
        self._states.update(states)

    async def verify_all(
        self, event_history: list[dict[str, Any]], *, timeout_ms: float = 5000.0
    ) -> VerificationReport:
        results: list[VerificationResult] = []
        start = time.perf_counter()

        for inv_id, invariant in self._invariants.items():
            elapsed = (time.perf_counter() - start) * 1000
            if elapsed > timeout_ms:
                results.append(VerificationResult(
                    invariant_id=inv_id,
                    status=VerificationStatus.TIMEOUT,
                    duration_ms=elapsed,
                ))
                continue

            result = await self._verify_invariant(invariant, event_history, timeout_ms - elapsed)
            results.append(result)

        deadlock_report = self._check_deadlocks()
        policy_report = self._check_policy_completeness(event_history)

        violated = sum(1 for r in results if r.status == VerificationStatus.VIOLATED)
        all_verified = violated == 0 and all(
            r.status == VerificationStatus.VERIFIED for r in results
        )

        return VerificationReport(
            results=tuple(results),
            deadlock_report=deadlock_report,
            policy_report=policy_report,
            all_verified=all_verified,
            total_invariants=len(results),
            violated_count=violated,
        )

    async def verify_single(
        self, invariant_id: str, event_history: list[dict[str, Any]]
    ) -> VerificationResult:
        invariant = self._invariants.get(invariant_id)
        if invariant is None:
            return VerificationResult(
                invariant_id=invariant_id,
                status=VerificationStatus.UNKNOWN,
                evidence={"error": "invariant not registered"},
            )
        return await self._verify_invariant(invariant, event_history, 5000.0)

    async def _verify_invariant(
        self,
        invariant: Invariant,
        event_history: list[dict[str, Any]],
        remaining_ms: float,
    ) -> VerificationResult:
        start = time.perf_counter()
        predicate = self._predicates[invariant.invariant_id]
        checked_states = 0
        checked_transitions = 0

        if invariant.kind == InvariantKind.STATE_INVARIANT:
            for i, event in enumerate(event_history):
                elapsed = (time.perf_counter() - start) * 1000
                if elapsed > remaining_ms:
                    return VerificationResult(
                        invariant_id=invariant.invariant_id,
                        status=VerificationStatus.TIMEOUT,
                        checked_states=checked_states,
                        duration_ms=elapsed,
                    )
                checked_states += 1
                if not await predicate(event):
                    return VerificationResult(
                        invariant_id=invariant.invariant_id,
                        status=VerificationStatus.VIOLATED,
                        counterexample=[event],
                        checked_states=checked_states,
                        evidence={"violated_at_index": i, "event": event},
                        duration_ms=(time.perf_counter() - start) * 1000,
                    )

        elif invariant.kind == InvariantKind.TRANSITION_INVARIANT:
            for i in range(len(event_history) - 1):
                elapsed = (time.perf_counter() - start) * 1000
                if elapsed > remaining_ms:
                    return VerificationResult(
                        invariant_id=invariant.invariant_id,
                        status=VerificationStatus.TIMEOUT,
                        checked_transitions=checked_transitions,
                        duration_ms=elapsed,
                    )
                checked_transitions += 1
                pair = {"before": event_history[i], "after": event_history[i + 1]}
                if not await predicate(pair):
                    return VerificationResult(
                        invariant_id=invariant.invariant_id,
                        status=VerificationStatus.VIOLATED,
                        counterexample=[event_history[i], event_history[i + 1]],
                        checked_transitions=checked_transitions,
                        evidence={"violated_at_index": i},
                        duration_ms=(time.perf_counter() - start) * 1000,
                    )

        elif invariant.kind == InvariantKind.SAFETY_PROPERTY:
            for i, event in enumerate(event_history):
                checked_states += 1
                if not await predicate(event):
                    return VerificationResult(
                        invariant_id=invariant.invariant_id,
                        status=VerificationStatus.VIOLATED,
                        counterexample=[event],
                        checked_states=checked_states,
                        evidence={"bad_state_reached_at": i},
                        duration_ms=(time.perf_counter() - start) * 1000,
                    )

        elif invariant.kind == InvariantKind.LIVENESS_PROPERTY:
            satisfied = False
            for event in event_history:
                checked_states += 1
                if await predicate(event):
                    satisfied = True
                    break
            if not satisfied:
                return VerificationResult(
                    invariant_id=invariant.invariant_id,
                    status=VerificationStatus.VIOLATED,
                    checked_states=checked_states,
                    evidence={"reason": "good state never reached"},
                    duration_ms=(time.perf_counter() - start) * 1000,
                )

        duration = (time.perf_counter() - start) * 1000
        return VerificationResult(
            invariant_id=invariant.invariant_id,
            status=VerificationStatus.VERIFIED,
            checked_states=checked_states,
            checked_transitions=checked_transitions,
            duration_ms=duration,
        )

    def _check_deadlocks(self) -> DeadlockReport:
        if not self._states:
            return DeadlockReport(has_deadlock=False)

        sink_states = [s for s in self._states if not self._adjacency.get(s)]
        terminal_ok = {"completed", "failed", "aborted", "archived"}
        deadlock_states = [s for s in sink_states if s not in terminal_ok]

        cycle_path = self._find_cycle()

        return DeadlockReport(
            has_deadlock=bool(deadlock_states) or bool(cycle_path),
            deadlock_states=tuple(deadlock_states),
            cycle_path=tuple(cycle_path) if cycle_path else (),
        )

    def _find_cycle(self) -> list[str] | None:
        visited: set[str] = set()
        rec_stack: set[str] = set()
        path: list[str] = []

        def dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in self._adjacency.get(node, []):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    cycle_start = path.index(neighbor)
                    path.append(neighbor)
                    del path[:cycle_start]
                    return True

            path.pop()
            rec_stack.discard(node)
            return False

        for state in self._states:
            if state not in visited:
                if dfs(state):
                    return path
        return None

    def _check_policy_completeness(
        self, event_history: list[dict[str, Any]]
    ) -> PolicyCompletenessReport:
        all_capabilities: set[str] = set()
        covered_capabilities: set[str] = set()

        for event in event_history:
            cap = event.get("capability")
            if cap:
                all_capabilities.add(cap)
            if event.get("event_type") in (
                "policy.evaluated", "grant.issued", "capability.checked"
            ):
                evaluated_cap = event.get("payload", {}).get("capability", "")
                if evaluated_cap:
                    covered_capabilities.add(evaluated_cap)

        uncovered = all_capabilities - covered_capabilities

        conflicting: list[tuple[str, str]] = []
        rules_by_cap: dict[str, list[str]] = defaultdict(list)
        for event in event_history:
            if event.get("event_type") == "policy.evaluated":
                payload = event.get("payload", {})
                cap = payload.get("capability", "")
                decision = payload.get("decision", "")
                if cap:
                    rules_by_cap[cap].append(decision)

        for cap, decisions in rules_by_cap.items():
            unique = set(decisions)
            if "allow" in unique and "deny" in unique:
                conflicting.append((cap, "allow/deny conflict"))

        return PolicyCompletenessReport(
            is_complete=len(uncovered) == 0 and len(conflicting) == 0,
            total_capabilities=len(all_capabilities),
            covered_capabilities=len(covered_capabilities),
            uncovered_capabilities=tuple(sorted(uncovered)),
            conflicting_rules=tuple(conflicting),
        )
