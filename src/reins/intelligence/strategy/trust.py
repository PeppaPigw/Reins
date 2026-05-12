from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reins.intelligence.types import (
    TrustLevel,
    TrustScore,
)

TRUST_THRESHOLDS: dict[TrustLevel, tuple[int, float]] = {
    TrustLevel.semi_auto: (5, 0.70),
    TrustLevel.auto: (20, 0.80),
    TrustLevel.full_autonomy: (50, 0.90),
}

HALF_LIFE_DAYS = 30.0
PRIOR = 1.0


class TrustModel:
    def __init__(self, store_path: Path) -> None:
        self._store_path = store_path
        self._store_path.mkdir(parents=True, exist_ok=True)
        self._journal_path = self._store_path / "trust_journal.jsonl"
        self._outcomes: dict[str, list[dict[str, Any]]] = {}
        self._demotions: dict[str, TrustLevel | None] = {}
        self._load_journal()

    def _load_journal(self) -> None:
        if not self._journal_path.exists():
            return
        for line in self._journal_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            self._apply_event(event)

    def _apply_event(self, event: dict[str, Any]) -> None:
        etype = event.get("event_type", "")
        payload = event.get("payload", {})

        if etype == "trust.outcome_recorded":
            domain = payload["domain"]
            if domain not in self._outcomes:
                self._outcomes[domain] = []
            self._outcomes[domain].append(payload)

        elif etype == "trust.hard_demotion":
            domain = payload["domain"]
            self._demotions[domain] = TrustLevel(payload["to_level"])

    def _append_event(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {
            "event_type": event_type,
            "timestamp": datetime.now(UTC).isoformat(),
            "payload": payload,
        }
        with self._journal_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._apply_event(event)

    def get_domain_trust(self, domain: str) -> TrustScore:
        now = datetime.now(UTC)
        outcomes = self._outcomes.get(domain, [])

        effective_successes = 0.0
        effective_failures = 0.0

        for outcome in outcomes:
            ts = outcome.get("timestamp", "")
            try:
                age_days = (now - datetime.fromisoformat(ts)).total_seconds() / 86400.0
            except (ValueError, TypeError):
                age_days = 0.0

            weight = math.exp(-age_days / HALF_LIFE_DAYS)
            if outcome.get("success"):
                effective_successes += weight
            else:
                severity = outcome.get("severity", 1.0)
                effective_failures += weight * severity

        score = effective_successes / (effective_successes + effective_failures + PRIOR)
        level = self._compute_level(domain, effective_successes, score)

        return TrustScore(
            domain=domain,
            level=level,
            score=score,
            effective_successes=effective_successes,
            effective_failures=effective_failures,
            last_updated=now.isoformat(),
        )

    def _compute_level(
        self, domain: str, effective_successes: float, score: float
    ) -> TrustLevel:
        if demotion := self._demotions.get(domain):
            return demotion

        level = TrustLevel.supervised
        for candidate_level in [TrustLevel.semi_auto, TrustLevel.auto, TrustLevel.full_autonomy]:
            min_count, min_rate = TRUST_THRESHOLDS[candidate_level]
            if effective_successes >= min_count and score >= min_rate:
                level = candidate_level
            else:
                break
        return level

    async def record_outcome(
        self, domain: str, success: bool, severity: float = 0.0
    ) -> None:
        self._append_event("trust.outcome_recorded", {
            "domain": domain,
            "success": success,
            "severity": severity,
            "timestamp": datetime.now(UTC).isoformat(),
        })

    async def hard_demote(self, domain: str, to_level: TrustLevel, reason: str) -> None:
        self._append_event("trust.hard_demotion", {
            "domain": domain,
            "to_level": to_level.value,
            "reason": reason,
            "timestamp": datetime.now(UTC).isoformat(),
        })

    async def clear_demotion(self, domain: str) -> None:
        self._demotions.pop(domain, None)

    @property
    def known_domains(self) -> list[str]:
        return list(self._outcomes.keys())
