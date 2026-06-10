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


class RuleEffect(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ESCALATE = "escalate"
    LOG = "log"
    THROTTLE = "throttle"


class ConditionOp(str, Enum):
    EQUALS = "eq"
    NOT_EQUALS = "neq"
    IN = "in"
    NOT_IN = "not_in"
    GREATER = "gt"
    LESS = "lt"
    CONTAINS = "contains"
    MATCHES = "matches"


class PolicyScope(str, Enum):
    GLOBAL = "global"
    AGENT = "agent"
    RESOURCE = "resource"
    ACTION = "action"


class Condition(BaseModel):
    model_config = ConfigDict(frozen=True)

    field: str
    op: ConditionOp
    value: Any


class PolicyRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_id: str = Field(default_factory=_new_ulid)
    name: str
    scope: PolicyScope = PolicyScope.GLOBAL
    conditions: list[Condition] = Field(default_factory=list)
    effect: RuleEffect = RuleEffect.DENY
    priority: int = 0
    enabled: bool = True
    description: str = ""


class PolicyEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)

    eval_id: str = Field(default_factory=_new_ulid)
    rule_id: str
    rule_name: str = ""
    effect: RuleEffect
    matched: bool = False
    context: dict[str, Any] = Field(default_factory=dict)
    evaluated_at: datetime = Field(default_factory=_utc_now)


class PolicySet(BaseModel):
    model_config = ConfigDict(frozen=True)

    set_id: str = Field(default_factory=_new_ulid)
    name: str
    rules: list[str] = Field(default_factory=list)
    default_effect: RuleEffect = RuleEffect.DENY


class PolicyDSLStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_rules: int = 0
    total_evaluations: int = 0
    total_policy_sets: int = 0
    by_effect: dict[str, int] = Field(default_factory=dict)
    by_scope: dict[str, int] = Field(default_factory=dict)
    match_rate: float = 0.0
