from __future__ import annotations

from collections import defaultdict

from reins.hypothesis.types import (
    Evidence,
    EvidenceKind,
    Experiment,
    Hypothesis,
    HypothesisStats,
    HypothesisStatus,
    TestOutcome,
)


class HypothesisEngine:
    """Bayesian hypothesis testing engine for agent reasoning.

    Agents form hypotheses about their environment, gather evidence,
    run experiments, and update beliefs using Bayes' rule. Supports
    competing hypotheses, evidence weighting, and convergence detection.
    """

    def __init__(self, support_threshold: float = 0.8,
                 refutation_threshold: float = 0.2,
                 min_evidence: int = 3) -> None:
        self._support_threshold = support_threshold
        self._refutation_threshold = refutation_threshold
        self._min_evidence = min_evidence
        self._hypotheses: dict[str, Hypothesis] = {}
        self._evidence: list[Evidence] = []
        self._experiments: list[Experiment] = []

    def propose(self, statement: str, prior: float = 0.5,
                domain: str = "") -> Hypothesis:
        h = Hypothesis(
            statement=statement,
            prior_probability=prior,
            posterior_probability=prior,
            domain=domain,
        )
        self._hypotheses[h.hypothesis_id] = h
        return h

    def add_evidence(self, hypothesis_id: str, kind: EvidenceKind,
                     description: str, likelihood_ratio: float = 2.0,
                     strength: float = 0.5) -> Evidence | None:
        h = self._hypotheses.get(hypothesis_id)
        if not h:
            return None

        evidence = Evidence(
            hypothesis_id=hypothesis_id,
            kind=kind,
            description=description,
            likelihood_ratio=likelihood_ratio,
            strength=strength,
        )
        self._evidence.append(evidence)

        self._update_posterior(hypothesis_id, evidence)
        self._check_status(hypothesis_id)
        return evidence

    def run_experiment(self, hypothesis_id: str, description: str,
                       outcome: TestOutcome, observations: list[str] | None = None) -> Experiment | None:
        h = self._hypotheses.get(hypothesis_id)
        if not h:
            return None

        experiment = Experiment(
            hypothesis_id=hypothesis_id,
            description=description,
            outcome=outcome,
            observations=tuple(observations or []),
        )
        self._experiments.append(experiment)

        if outcome == TestOutcome.PASS:
            kind = EvidenceKind.CONFIRMING
            lr = 3.0
        elif outcome == TestOutcome.FAIL:
            kind = EvidenceKind.DISCONFIRMING
            lr = 0.3
        elif outcome == TestOutcome.PARTIAL:
            kind = EvidenceKind.NEUTRAL
            lr = 1.2
        else:
            kind = EvidenceKind.ANOMALOUS
            lr = 0.8

        self.add_evidence(hypothesis_id, kind, f"Experiment: {description}",
                          likelihood_ratio=lr)
        return experiment

    def get_hypothesis(self, hypothesis_id: str) -> Hypothesis | None:
        return self._hypotheses.get(hypothesis_id)

    def get_evidence_for(self, hypothesis_id: str) -> list[Evidence]:
        return [e for e in self._evidence if e.hypothesis_id == hypothesis_id]

    def get_competing(self, domain: str) -> list[Hypothesis]:
        return sorted(
            [h for h in self._hypotheses.values() if h.domain == domain],
            key=lambda h: -h.posterior_probability,
        )

    def get_best_hypothesis(self, domain: str) -> Hypothesis | None:
        competing = self.get_competing(domain)
        return competing[0] if competing else None

    def get_supported(self) -> list[Hypothesis]:
        return [h for h in self._hypotheses.values()
                if h.status == HypothesisStatus.SUPPORTED]

    def get_refuted(self) -> list[Hypothesis]:
        return [h for h in self._hypotheses.values()
                if h.status == HypothesisStatus.REFUTED]

    def get_stats(self) -> HypothesisStats:
        by_status: dict[str, int] = defaultdict(int)
        posteriors = []
        for h in self._hypotheses.values():
            by_status[h.status.value] += 1
            posteriors.append(h.posterior_probability)

        avg_post = sum(posteriors) / len(posteriors) if posteriors else 0.5

        return HypothesisStats(
            total_hypotheses=len(self._hypotheses),
            supported=by_status.get("supported", 0),
            refuted=by_status.get("refuted", 0),
            testing=by_status.get("testing", 0),
            total_evidence=len(self._evidence),
            total_experiments=len(self._experiments),
            avg_posterior=avg_post,
            by_status=dict(by_status),
        )

    def _update_posterior(self, hypothesis_id: str, evidence: Evidence) -> None:
        h = self._hypotheses[hypothesis_id]
        prior = h.posterior_probability

        lr = evidence.likelihood_ratio
        if evidence.kind == EvidenceKind.DISCONFIRMING:
            lr = min(lr, 1.0)
        elif evidence.kind == EvidenceKind.CONFIRMING:
            lr = max(lr, 1.0)

        posterior = (prior * lr) / (prior * lr + (1 - prior))
        posterior = max(0.01, min(0.99, posterior))

        updated = Hypothesis(
            hypothesis_id=h.hypothesis_id,
            statement=h.statement,
            prior_probability=h.prior_probability,
            posterior_probability=posterior,
            status=h.status,
            domain=h.domain,
            created_at=h.created_at,
        )
        self._hypotheses[hypothesis_id] = updated

    def _check_status(self, hypothesis_id: str) -> None:
        h = self._hypotheses[hypothesis_id]
        evidence_count = sum(1 for e in self._evidence if e.hypothesis_id == hypothesis_id)

        if evidence_count < self._min_evidence:
            new_status = HypothesisStatus.TESTING
        elif h.posterior_probability >= self._support_threshold:
            new_status = HypothesisStatus.SUPPORTED
        elif h.posterior_probability <= self._refutation_threshold:
            new_status = HypothesisStatus.REFUTED
        else:
            new_status = HypothesisStatus.TESTING

        if new_status != h.status:
            updated = Hypothesis(
                hypothesis_id=h.hypothesis_id,
                statement=h.statement,
                prior_probability=h.prior_probability,
                posterior_probability=h.posterior_probability,
                status=new_status,
                domain=h.domain,
                created_at=h.created_at,
            )
            self._hypotheses[hypothesis_id] = updated
