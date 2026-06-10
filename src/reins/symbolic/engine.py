from __future__ import annotations

from collections import defaultdict

from reins.symbolic.types import (
    Clause,
    InferenceRule,
    KnowledgeBase,
    ProofResult,
    ProofStatus,
    ProofStep,
    SymbolicStats,
    Term,
    TermKind,
)


class SymbolicReasoner:
    """First-order logic reasoning with unification, resolution, and backward chaining.

    Provides formal deductive reasoning capabilities: agents can assert facts,
    define rules, and prove queries using sound inference. This enables
    verifiable reasoning chains, not just pattern matching.
    """

    def __init__(self, max_depth: int = 50) -> None:
        self._facts: set[str] = set()
        self._rules: list[tuple[tuple[str, ...], str]] = []
        self._max_depth = max_depth
        self._results: list[ProofResult] = []

    def assert_fact(self, fact: str) -> None:
        self._facts.add(fact)

    def retract_fact(self, fact: str) -> bool:
        if fact in self._facts:
            self._facts.discard(fact)
            return True
        return False

    def get_facts(self) -> list[str]:
        return sorted(self._facts)

    def add_rule(self, premises: list[str], conclusion: str) -> None:
        self._rules.append((tuple(premises), conclusion))

    def get_rules(self) -> list[tuple[tuple[str, ...], str]]:
        return list(self._rules)

    def prove(self, query: str) -> ProofResult:
        steps: list[ProofStep] = []
        substitutions: dict[str, str] = {}
        proved = self._backward_chain(query, steps, substitutions, set(), 0)

        status = ProofStatus.PROVED if proved else ProofStatus.UNKNOWN
        result = ProofResult(
            query=query,
            status=status,
            steps=tuple(steps),
            depth=len(steps),
            substitutions=substitutions,
        )
        self._results.append(result)
        return result

    def prove_all(self, queries: list[str]) -> list[ProofResult]:
        return [self.prove(q) for q in queries]

    def query_with_variable(self, pattern: str, variable: str) -> list[str]:
        """Find all bindings for a variable in a pattern like 'parent(X, bob)'."""
        results = []
        pred_name, args_str = self._parse_predicate(pattern)
        if not pred_name:
            return results

        args = [a.strip() for a in args_str.split(",")]
        var_idx = -1
        for i, a in enumerate(args):
            if a == variable:
                var_idx = i
                break

        if var_idx == -1:
            return results

        for fact in self._facts:
            fact_pred, fact_args_str = self._parse_predicate(fact)
            if fact_pred != pred_name:
                continue
            fact_args = [a.strip() for a in fact_args_str.split(",")]
            if len(fact_args) != len(args):
                continue
            match = True
            for i, (pattern_arg, fact_arg) in enumerate(zip(args, fact_args)):
                if i == var_idx:
                    continue
                if pattern_arg != fact_arg and not pattern_arg[0].isupper():
                    match = False
                    break
            if match:
                results.append(fact_args[var_idx])

        return results

    def is_consistent(self) -> bool:
        """Check if the knowledge base contains no contradictions."""
        for fact in self._facts:
            negated = f"not_{fact}" if not fact.startswith("not_") else fact[4:]
            if negated in self._facts:
                return False
        return True

    def forward_chain(self) -> list[str]:
        """Derive all new facts from existing facts and rules."""
        derived: list[str] = []
        changed = True
        while changed:
            changed = False
            for premises, conclusion in self._rules:
                if conclusion in self._facts:
                    continue
                if all(self._matches_any_fact(p) for p in premises):
                    self._facts.add(conclusion)
                    derived.append(conclusion)
                    changed = True
        return derived

    def unify(self, term1: str, term2: str) -> dict[str, str] | None:
        """Attempt to unify two terms, returning substitution or None."""
        return self._unify_terms(term1, term2, {})

    def get_stats(self) -> SymbolicStats:
        by_status: dict[str, int] = defaultdict(int)
        depths = []
        for r in self._results:
            by_status[r.status.value] += 1
            if r.status == ProofStatus.PROVED:
                depths.append(r.depth)

        proofs_found = sum(1 for r in self._results if r.status == ProofStatus.PROVED)
        avg_depth = sum(depths) / len(depths) if depths else 0.0

        return SymbolicStats(
            total_facts=len(self._facts),
            total_rules=len(self._rules),
            total_queries=len(self._results),
            proofs_found=proofs_found,
            avg_proof_depth=avg_depth,
            by_status=dict(by_status),
        )

    def _backward_chain(self, goal: str, steps: list[ProofStep],
                        subs: dict[str, str], visited: set[str],
                        depth: int) -> bool:
        if depth > self._max_depth:
            return False
        if goal in visited:
            return False

        visited.add(goal)

        if self._matches_any_fact(goal):
            steps.append(ProofStep(
                rule=InferenceRule.UNIVERSAL_INSTANTIATION,
                conclusion=goal,
            ))
            return True

        for premises, conclusion in self._rules:
            unifier = self._unify_terms(conclusion, goal, {})
            if unifier is not None:
                applied_premises = [self._apply_substitution(p, unifier) for p in premises]
                all_proved = True
                for premise in applied_premises:
                    if not self._backward_chain(premise, steps, subs, set(visited), depth + 1):
                        all_proved = False
                        break

                if all_proved:
                    steps.append(ProofStep(
                        rule=InferenceRule.MODUS_PONENS,
                        premises=tuple(applied_premises),
                        conclusion=goal,
                        substitution=unifier,
                    ))
                    subs.update(unifier)
                    return True

        visited.discard(goal)
        return False

    def _matches_any_fact(self, pattern: str) -> bool:
        if pattern in self._facts:
            return True
        for fact in self._facts:
            if self._unify_terms(pattern, fact, {}) is not None:
                return True
        return False

    def _unify_terms(self, t1: str, t2: str, subs: dict[str, str]) -> dict[str, str] | None:
        t1 = self._apply_substitution(t1, subs)
        t2 = self._apply_substitution(t2, subs)

        if t1 == t2:
            return dict(subs)

        if self._is_variable(t1):
            return self._unify_var(t1, t2, subs)
        if self._is_variable(t2):
            return self._unify_var(t2, t1, subs)

        pred1, args1_str = self._parse_predicate(t1)
        pred2, args2_str = self._parse_predicate(t2)

        if not pred1 or not pred2 or pred1 != pred2:
            return None

        args1 = [a.strip() for a in args1_str.split(",")] if args1_str else []
        args2 = [a.strip() for a in args2_str.split(",")] if args2_str else []

        if len(args1) != len(args2):
            return None

        result = dict(subs)
        for a1, a2 in zip(args1, args2):
            unified = self._unify_terms(a1, a2, result)
            if unified is None:
                return None
            result = unified

        return result

    def _unify_var(self, var: str, term: str, subs: dict[str, str]) -> dict[str, str] | None:
        if var in subs:
            return self._unify_terms(subs[var], term, subs)
        if term in subs:
            return self._unify_terms(var, subs[term], subs)
        if var in term:
            return None
        new_subs = dict(subs)
        new_subs[var] = term
        return new_subs

    def _apply_substitution(self, term: str, subs: dict[str, str]) -> str:
        result = term
        for var, val in subs.items():
            result = result.replace(var, val)
        return result

    def _is_variable(self, term: str) -> bool:
        if not term:
            return False
        if "(" in term:
            return False
        return term[0].isupper()

    def _parse_predicate(self, term: str) -> tuple[str, str]:
        if "(" not in term:
            return "", ""
        idx = term.index("(")
        pred = term[:idx]
        args = term[idx + 1:-1] if term.endswith(")") else ""
        return pred, args
