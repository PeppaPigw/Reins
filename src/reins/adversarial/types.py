from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

import ulid
from pydantic import BaseModel, ConfigDict, Field


def _new_ulid() -> str:
    return str(ulid.new())


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AttackCategory(str, Enum):
    PROMPT_INJECTION = "prompt_injection"
    JAILBREAK = "jailbreak"
    DATA_EXFILTRATION = "data_exfiltration"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    RESOURCE_ABUSE = "resource_abuse"
    OUTPUT_MANIPULATION = "output_manipulation"
    CONTEXT_POISONING = "context_poisoning"
    BOUNDARY_VIOLATION = "boundary_violation"


class AttackSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFORMATIONAL = "informational"


class ProbeResult(str, Enum):
    BLOCKED = "blocked"
    DETECTED = "detected"
    PARTIAL_SUCCESS = "partial_success"
    FULL_BYPASS = "full_bypass"
    ERROR = "error"


class AttackPattern(BaseModel):
    model_config = ConfigDict(frozen=True)

    pattern_id: str = Field(default_factory=_new_ulid)
    category: AttackCategory
    name: str
    description: str = ""
    severity: AttackSeverity = AttackSeverity.MEDIUM
    payload: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProbeAttempt(BaseModel):
    model_config = ConfigDict(frozen=True)

    attempt_id: str = Field(default_factory=_new_ulid)
    pattern_id: str
    target_id: str
    result: ProbeResult
    response: str = ""
    latency_ms: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)
    attempted_at: datetime = Field(default_factory=_utc_now)


class Vulnerability(BaseModel):
    model_config = ConfigDict(frozen=True)

    vuln_id: str = Field(default_factory=_new_ulid)
    target_id: str
    category: AttackCategory
    severity: AttackSeverity
    pattern_id: str
    description: str = ""
    evidence: str = ""
    discovered_at: datetime = Field(default_factory=_utc_now)


class RobustnessScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    target_id: str
    overall_score: float = 0.0
    by_category: dict[str, float] = Field(default_factory=dict)
    total_probes: int = 0
    blocked_count: int = 0
    bypassed_count: int = 0


class AdversarialStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_patterns: int = 0
    total_probes: int = 0
    total_vulnerabilities: int = 0
    targets_tested: int = 0
    avg_robustness: float = 0.0
    by_category: dict[str, int] = Field(default_factory=dict)
    by_severity: dict[str, int] = Field(default_factory=dict)
