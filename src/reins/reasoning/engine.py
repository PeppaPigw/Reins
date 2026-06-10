from __future__ import annotations

from collections import defaultdict

from reins.reasoning.types import (
    Argument,
    ArgumentStrength,
    Contradiction,
    InferenceRule,
    InferenceStep,
    LogicKind,
    Proposition,
    PropositionStatus,
    ReasoningStats,
)


class ReasoningEngine:
    """Formal logical reasoning with inference chains and consistency checking.

    Manages propositions, inference rules, argument construction,
    contradiction detection, and belief revision through logical derivation.
    """

    def __init__(self) -> None:
        self._propositions: dict[str, Proposition] = {}
        self._rules: dict[str, InferenceRule] = {}
        self._steps: list[InferenceStep] = []
        self._arguments: dict[str, Argument] = {}
        self._contradictions: list[Contradiction] = []

    def assert_proposition(self, statement: str, confidence: float = 1.0,
                           source: str = "") -> Proposition:
        prop = Proposition(statement=statement, confidence=confidence, source=source)
        self._propositions[prop.prop_id] = prop
        self._check_contradictions(prop)
        return prop

    def get_proposition(self, prop_id: str) -> Proposition | None:
        return self._propositions.get(prop_id)

    def retract_proposition(self, prop_id: str) -> Proposition | None:
        prop = self._propositions.get(prop_id)
        if not prop:
            return None
        updated = prop.model_copy(update={"status": PropositionStatus.RETRACTED})
        self._propositions[prop_id] = updated
        return updated

    def get_active_propositions(self) -> list[Proposition]:
        return [
            p for p in self._propositions.values()
            if p.status not in (PropositionStatus.RETRACTED, PropositionStatus.CONTRADICTED)
        ]

    def register_rule(self, name: str, premises: list[str], conclusion: str,
                      kind: LogicKind = LogicKind.DEDUCTIVE,
                      strength: float = 1.0) -> InferenceRule:
        rule = InferenceRule(
            name=name,
            premises=tuple(premises),
            conclusion=conclusion,
            kind=kind,
            strength=strength,
        )
        self._rules[rule.rule_id] = rule
        return rule

    def get_rule(self, rule_id: str) -> InferenceRule | None:
        return self._rules.get(rule_id)

    def apply_rule(self, rule_id: str, premise_ids: list[str]) -> Proposition | None:
        rule = self._rules.get(rule_id)
        if not rule:
            return None

        premises = [self._propositions.get(pid) for pid in premise_ids]
        if any(p is None for p in premises):
            return None
        if any(p.status == PropositionStatus.RETRACTED for p in premises):
            return None

        min_confidence = min(p.confidence for p in premises)
        derived_confidence = min_confidence * rule.strength

        conclusion = Proposition(
            statement=rule.conclusion,
            status=PropositionStatus.DERIVED,
            confidence=derived_confidence,
            source=f"rule:{rule.name}",
        )
        self._propositions[conclusion.prop_id] = conclusion

        step = InferenceStep(
            rule_id=rule_id,
            premises_used=tuple(premise_ids),
            conclusion_id=conclusion.prop_id,
            confidence=derived_confidence,
        )
        self._steps.append(step)

        self._check_contradictions(conclusion)
        return conclusion

    def build_argument(self, claim: str, premise_ids: list[str]) -> Argument:
        premises = [self._propositions.get(pid) for pid in premise_ids]
        valid_premises = [p for p in premises if p is not None]

        if not valid_premises:
            strength = ArgumentStrength.FALLACIOUS
            confidence = 0.0
        else:
            avg_conf = sum(p.confidence for p in valid_premises) / len(valid_premises)
            confidence = avg_conf
            strength = self._classify_strength(avg_conf, len(valid_premises))

        relevant_steps = [
            s.step_id for s in self._steps
            if any(pid in s.premises_used for pid in premise_ids)
        ]

        argument = Argument(
            claim=claim,
            premises=tuple(premise_ids),
            steps=tuple(relevant_steps),
            strength=strength,
            confidence=confidence,
        )
        self._arguments[argument.argument_id] = argument
        return argument

    def get_argument(self, argument_id: str) -> Argument | None:
        return self._arguments.get(argument_id)

    def get_contradictions(self, unresolved_only: bool = False) -> list[Contradiction]:
        if unresolved_only:
            return [c for c in self._contradictions if not c.resolved]
        return list(self._contradictions)

    def resolve_contradiction(self, contradiction_id: str,
                              retract_prop_id: str) -> Contradiction | None:
        for i, c in enumerate(self._contradictions):
            if c.contradiction_id == contradiction_id:
                self.retract_proposition(retract_prop_id)
                resolved = c.model_copy(update={"resolved": True})
                self._contradictions[i] = resolved
                return resolved
        return None

    def get_inference_chain(self, prop_id: str) -> list[InferenceStep]:
        chain: list[InferenceStep] = []
        visited: set[str] = set()
        self._trace_chain(prop_id, chain, visited)
        return chain

    def forward_chain(self) -> list[Proposition]:
        derived: list[Proposition] = []
        active_statements = {p.statement for p in self.get_active_propositions()}

        for rule in self._rules.values():
            if rule.conclusion in active_statements:
                continue
            premise_matches = []
            for premise_pattern in rule.premises:
                matching = [
                    p for p in self.get_active_propositions()
                    if premise_pattern.lower() in p.statement.lower()
                ]
                if matching:
                    premise_matches.append(matching[0].prop_id)
                else:
                    break

            if len(premise_matches) == len(rule.premises):
                result = self.apply_rule(rule.rule_id, premise_matches)
                if result:
                    derived.append(result)

        return derived

    def get_stats(self) -> ReasoningStats:
        by_kind: dict[str, int] = defaultdict(int)
        for rule in self._rules.values():
            by_kind[rule.kind.value] += 1

        active = self.get_active_propositions()
        avg_conf = (
            sum(p.confidence for p in active) / len(active) if active else 0.0
        )
        resolved = sum(1 for c in self._contradictions if c.resolved)

        return ReasoningStats(
            total_propositions=len(self._propositions),
            total_rules=len(self._rules),
            total_inferences=len(self._steps),
            total_arguments=len(self._arguments),
            contradictions_found=len(self._contradictions),
            contradictions_resolved=resolved,
            avg_confidence=avg_conf,
            by_logic_kind=dict(by_kind),
        )

    def _check_contradictions(self, new_prop: Proposition) -> None:
        negation_markers = ["not ", "no ", "never ", "cannot ", "impossible "]
        for existing in self._propositions.values():
            if existing.prop_id == new_prop.prop_id:
                continue
            if existing.status in (PropositionStatus.RETRACTED, PropositionStatus.CONTRADICTED):
                continue
            if self._is_contradictory(new_prop.statement, existing.statement, negation_markers):
                self._contradictions.append(Contradiction(
                    prop_a=new_prop.prop_id,
                    prop_b=existing.prop_id,
                    description=f"'{new_prop.statement}' contradicts '{existing.statement}'",
                ))

    def _is_contradictory(self, stmt_a: str, stmt_b: str,
                          markers: list[str]) -> bool:
        a_lower = stmt_a.lower().strip()
        b_lower = stmt_b.lower().strip()

        for marker in markers:
            if a_lower.startswith(marker) and a_lower[len(marker):] == b_lower:
                return True
            if b_lower.startswith(marker) and b_lower[len(marker):] == a_lower:
                return True
        return False

    def _classify_strength(self, confidence: float,
                           premise_count: int) -> ArgumentStrength:
        if confidence >= 0.95 and premise_count >= 2:
            return ArgumentStrength.CONCLUSIVE
        if confidence >= 0.8:
            return ArgumentStrength.STRONG
        if confidence >= 0.5:
            return ArgumentStrength.MODERATE
        if confidence >= 0.2:
            return ArgumentStrength.WEAK
        return ArgumentStrength.FALLACIOUS

    def _trace_chain(self, prop_id: str, chain: list[InferenceStep],
                     visited: set[str]) -> None:
        if prop_id in visited:
            return
        visited.add(prop_id)
        for step in self._steps:
            if step.conclusion_id == prop_id:
                chain.append(step)
                for premise_id in step.premises_used:
                    self._trace_chain(premise_id, chain, visited)
