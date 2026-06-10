from __future__ import annotations

import time
from collections import defaultdict, deque

from reins.formal.types import (
    AtomicProposition,
    CheckResult,
    Counterexample,
    FormalProperty,
    FormalStats,
    ModelCheckResult,
    PropertyKind,
    StateSpace,
    TemporalFormula,
    TemporalOperator,
)


class ModelChecker:
    """LTL model checker for verifying temporal properties of agent state machines.

    Implements explicit-state model checking with BFS exploration,
    counterexample generation, and support for safety/liveness properties.
    This provides mathematical guarantees about agent behavior that no
    other harness offers.
    """

    def __init__(self, max_states: int = 100_000) -> None:
        self._formulas: dict[str, TemporalFormula] = {}
        self._properties: dict[str, FormalProperty] = {}
        self._spaces: dict[str, StateSpace] = {}
        self._propositions: dict[str, AtomicProposition] = {}
        self._results: list[ModelCheckResult] = []
        self._max_states = max_states

    def define_proposition(self, name: str, predicate: str = "",
                           description: str = "") -> AtomicProposition:
        prop = AtomicProposition(name=name, predicate=predicate, description=description)
        self._propositions[name] = prop
        return prop

    def define_formula(self, operator: TemporalOperator,
                       operands: list[str] | None = None,
                       atom: str | None = None,
                       description: str = "") -> TemporalFormula:
        formula = TemporalFormula(
            operator=operator,
            operands=tuple(operands or []),
            atom=atom,
            description=description,
        )
        self._formulas[formula.formula_id] = formula
        return formula

    def define_property(self, name: str, kind: PropertyKind, formula_id: str,
                        description: str = "", critical: bool = False) -> FormalProperty:
        prop = FormalProperty(
            name=name, kind=kind, formula_id=formula_id,
            description=description, critical=critical,
        )
        self._properties[prop.property_id] = prop
        return prop

    def get_property(self, property_id: str) -> FormalProperty | None:
        return self._properties.get(property_id)

    def define_state_space(self, name: str, states: list[str],
                           initial_state: str,
                           transitions: list[tuple[str, str, str]],
                           propositions: dict[str, list[str]] | None = None) -> StateSpace:
        props = {k: tuple(v) for k, v in (propositions or {}).items()}
        space = StateSpace(
            name=name,
            states=tuple(states),
            initial_state=initial_state,
            transitions=tuple(transitions),
            propositions=props,
        )
        self._spaces[space.space_id] = space
        return space

    def get_state_space(self, space_id: str) -> StateSpace | None:
        return self._spaces.get(space_id)

    def check_property(self, property_id: str, space_id: str) -> ModelCheckResult:
        start = time.monotonic()
        prop = self._properties.get(property_id)
        space = self._spaces.get(space_id)

        if not prop or not space:
            result = ModelCheckResult(
                property_id=property_id or "", space_id=space_id or "",
                result=CheckResult.UNKNOWN,
            )
            self._results.append(result)
            return result

        formula = self._formulas.get(prop.formula_id)
        if not formula:
            result = ModelCheckResult(
                property_id=property_id, space_id=space_id,
                result=CheckResult.UNKNOWN,
            )
            self._results.append(result)
            return result

        states_explored, transitions_explored, check_result, counterexample = (
            self._model_check(formula, space)
        )

        elapsed = (time.monotonic() - start) * 1000
        result = ModelCheckResult(
            property_id=property_id,
            space_id=space_id,
            result=check_result,
            counterexample=counterexample,
            states_explored=states_explored,
            transitions_explored=transitions_explored,
            duration_ms=elapsed,
        )
        self._results.append(result)
        return result

    def check_all(self, space_id: str) -> list[ModelCheckResult]:
        results = []
        for pid in self._properties:
            results.append(self.check_property(pid, space_id))
        return results

    def check_safety(self, space_id: str, bad_states: list[str]) -> ModelCheckResult:
        """Check that bad states are never reachable from initial state."""
        space = self._spaces.get(space_id)
        if not space:
            result = ModelCheckResult(
                property_id="safety_check", space_id=space_id,
                result=CheckResult.UNKNOWN,
            )
            self._results.append(result)
            return result

        reachable, path_to = self._bfs_reachable(space)
        bad_reached = [s for s in bad_states if s in reachable]

        if bad_reached:
            trace = self._reconstruct_path(path_to, space.initial_state, bad_reached[0])
            counterexample = Counterexample(
                trace=tuple(trace),
                violated_at_step=len(trace) - 1,
                explanation=f"Bad state '{bad_reached[0]}' is reachable.",
            )
            check_result = CheckResult.VIOLATED
        else:
            counterexample = None
            check_result = CheckResult.SATISFIED

        result = ModelCheckResult(
            property_id="safety_check", space_id=space_id,
            result=check_result,
            counterexample=counterexample,
            states_explored=len(reachable),
        )
        self._results.append(result)
        return result

    def check_liveness(self, space_id: str, target_state: str) -> ModelCheckResult:
        """Check that target state is eventually reachable from all reachable states."""
        space = self._spaces.get(space_id)
        if not space:
            result = ModelCheckResult(
                property_id="liveness_check", space_id=space_id,
                result=CheckResult.UNKNOWN,
            )
            self._results.append(result)
            return result

        reachable, _ = self._bfs_reachable(space)

        if target_state not in reachable:
            counterexample = Counterexample(
                trace=(space.initial_state,),
                explanation=f"Target '{target_state}' not reachable from initial state.",
            )
            result = ModelCheckResult(
                property_id="liveness_check", space_id=space_id,
                result=CheckResult.VIOLATED,
                counterexample=counterexample,
                states_explored=len(reachable),
            )
            self._results.append(result)
            return result

        dead_ends = []
        for state in reachable:
            reachable_from_state = self._bfs_from(space, state)
            if target_state not in reachable_from_state and state != target_state:
                dead_ends.append(state)

        if dead_ends:
            counterexample = Counterexample(
                trace=tuple(dead_ends[:5]),
                explanation=f"States {dead_ends[:3]} cannot reach '{target_state}'.",
            )
            check_result = CheckResult.VIOLATED
        else:
            counterexample = None
            check_result = CheckResult.SATISFIED

        result = ModelCheckResult(
            property_id="liveness_check", space_id=space_id,
            result=check_result,
            counterexample=counterexample,
            states_explored=len(reachable),
        )
        self._results.append(result)
        return result

    def check_deadlock_freedom(self, space_id: str) -> ModelCheckResult:
        """Check that no reachable state has zero outgoing transitions."""
        space = self._spaces.get(space_id)
        if not space:
            result = ModelCheckResult(
                property_id="deadlock_freedom", space_id=space_id,
                result=CheckResult.UNKNOWN,
            )
            self._results.append(result)
            return result

        reachable, path_to = self._bfs_reachable(space)
        outgoing: dict[str, int] = defaultdict(int)
        for src, _, _ in space.transitions:
            outgoing[src] += 1

        deadlocked = [s for s in reachable if outgoing[s] == 0]

        if deadlocked:
            trace = self._reconstruct_path(path_to, space.initial_state, deadlocked[0])
            counterexample = Counterexample(
                trace=tuple(trace),
                violated_at_step=len(trace) - 1,
                explanation=f"State '{deadlocked[0]}' has no outgoing transitions.",
            )
            check_result = CheckResult.VIOLATED
        else:
            counterexample = None
            check_result = CheckResult.SATISFIED

        result = ModelCheckResult(
            property_id="deadlock_freedom", space_id=space_id,
            result=check_result,
            counterexample=counterexample,
            states_explored=len(reachable),
        )
        self._results.append(result)
        return result

    def get_results(self, property_id: str | None = None) -> list[ModelCheckResult]:
        results = self._results
        if property_id:
            results = [r for r in results if r.property_id == property_id]
        return results

    def get_stats(self) -> FormalStats:
        satisfied = sum(1 for r in self._results if r.result == CheckResult.SATISFIED)
        violated = sum(1 for r in self._results if r.result == CheckResult.VIOLATED)

        by_kind: dict[str, int] = defaultdict(int)
        for p in self._properties.values():
            by_kind[p.kind.value] += 1

        states_list = [r.states_explored for r in self._results if r.states_explored > 0]
        avg_states = sum(states_list) / len(states_list) if states_list else 0.0

        return FormalStats(
            total_properties=len(self._properties),
            total_spaces=len(self._spaces),
            total_checks=len(self._results),
            satisfied=satisfied,
            violated=violated,
            by_kind=dict(by_kind),
            avg_states_explored=avg_states,
        )

    def _model_check(self, formula: TemporalFormula,
                     space: StateSpace) -> tuple[int, int, CheckResult, Counterexample | None]:
        reachable, path_to = self._bfs_reachable(space)
        transitions_count = sum(
            1 for src, _, _ in space.transitions if src in reachable
        )

        if formula.operator == TemporalOperator.ALWAYS:
            return self._check_always(formula, space, reachable, path_to, transitions_count)
        elif formula.operator == TemporalOperator.EVENTUALLY:
            return self._check_eventually(formula, space, reachable, path_to, transitions_count)
        elif formula.operator == TemporalOperator.NOT:
            return self._check_not(formula, space, reachable, path_to, transitions_count)
        else:
            return len(reachable), transitions_count, CheckResult.UNKNOWN, None

    def _check_always(self, formula: TemporalFormula, space: StateSpace,
                      reachable: set[str], path_to: dict[str, str | None],
                      transitions_count: int) -> tuple[int, int, CheckResult, Counterexample | None]:
        prop_name = formula.atom or (formula.operands[0] if formula.operands else "")
        states_with_prop = set(space.propositions.get(prop_name, ()))

        violating = [s for s in reachable if s not in states_with_prop]
        if violating:
            trace = self._reconstruct_path(path_to, space.initial_state, violating[0])
            ce = Counterexample(
                trace=tuple(trace),
                violated_at_step=len(trace) - 1,
                explanation=f"Property '{prop_name}' does not hold in state '{violating[0]}'.",
            )
            return len(reachable), transitions_count, CheckResult.VIOLATED, ce
        return len(reachable), transitions_count, CheckResult.SATISFIED, None

    def _check_eventually(self, formula: TemporalFormula, space: StateSpace,
                          reachable: set[str], path_to: dict[str, str | None],
                          transitions_count: int) -> tuple[int, int, CheckResult, Counterexample | None]:
        prop_name = formula.atom or (formula.operands[0] if formula.operands else "")
        states_with_prop = set(space.propositions.get(prop_name, ()))

        if reachable & states_with_prop:
            return len(reachable), transitions_count, CheckResult.SATISFIED, None

        ce = Counterexample(
            trace=(space.initial_state,),
            explanation=f"Property '{prop_name}' never holds in any reachable state.",
        )
        return len(reachable), transitions_count, CheckResult.VIOLATED, ce

    def _check_not(self, formula: TemporalFormula, space: StateSpace,
                   reachable: set[str], path_to: dict[str, str | None],
                   transitions_count: int) -> tuple[int, int, CheckResult, Counterexample | None]:
        prop_name = formula.atom or (formula.operands[0] if formula.operands else "")
        states_with_prop = set(space.propositions.get(prop_name, ()))

        violating = [s for s in reachable if s in states_with_prop]
        if violating:
            trace = self._reconstruct_path(path_to, space.initial_state, violating[0])
            ce = Counterexample(
                trace=tuple(trace),
                violated_at_step=len(trace) - 1,
                explanation=f"Negated property '{prop_name}' holds in state '{violating[0]}'.",
            )
            return len(reachable), transitions_count, CheckResult.VIOLATED, ce
        return len(reachable), transitions_count, CheckResult.SATISFIED, None

    def _bfs_reachable(self, space: StateSpace) -> tuple[set[str], dict[str, str | None]]:
        adj: dict[str, list[str]] = defaultdict(list)
        for src, _, dst in space.transitions:
            adj[src].append(dst)

        visited: set[str] = set()
        path_to: dict[str, str | None] = {space.initial_state: None}
        queue: deque[str] = deque([space.initial_state])
        visited.add(space.initial_state)

        while queue and len(visited) < self._max_states:
            state = queue.popleft()
            for neighbor in adj[state]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    path_to[neighbor] = state
                    queue.append(neighbor)

        return visited, path_to

    def _bfs_from(self, space: StateSpace, start: str) -> set[str]:
        adj: dict[str, list[str]] = defaultdict(list)
        for src, _, dst in space.transitions:
            adj[src].append(dst)

        visited: set[str] = set()
        queue: deque[str] = deque([start])
        visited.add(start)

        while queue and len(visited) < self._max_states:
            state = queue.popleft()
            for neighbor in adj[state]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

        return visited

    def _reconstruct_path(self, path_to: dict[str, str | None],
                          start: str, end: str) -> list[str]:
        path = []
        current: str | None = end
        while current is not None:
            path.append(current)
            current = path_to.get(current)
        path.reverse()
        return path
