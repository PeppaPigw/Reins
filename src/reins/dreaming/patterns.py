from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any, Iterable

from reins.dreaming.types import (
    ActionRecord,
    FailureRecord,
    Pattern,
    PatternKind,
    SessionSummary,
    SuccessRecord,
)

MAX_SEQUENCE_LENGTH = 6
MIN_PATTERN_CONFIDENCE = 0.35


class PatternExtractor:
    """Extracts recurring patterns from event journals."""

    def __init__(self, *, max_sequence_length: int = MAX_SEQUENCE_LENGTH) -> None:
        self._max_sequence_length = max_sequence_length

    async def extract(self, session: SessionSummary) -> list[Pattern]:
        actions = _actions_from_session(session)
        failures = _failures_from_session(session, actions)
        successes = _successes_from_session(session, actions)

        patterns: list[Pattern] = []
        patterns.extend(await self.extract_success_sequences(session, successes, actions))
        patterns.extend(await self.extract_failure_sequences(session, failures, actions))
        patterns.extend(
            await self.extract_tool_usage_patterns(session, successes, failures, actions)
        )
        patterns.extend(await self.extract_context_patterns(session, successes, failures))
        patterns.extend(await self.extract_temporal_patterns(session, successes, failures))
        return [pattern for pattern in patterns if pattern.confidence >= MIN_PATTERN_CONFIDENCE]

    async def extract_success_sequences(
        self,
        session: SessionSummary,
        successes: list[SuccessRecord],
        actions: list[ActionRecord],
    ) -> list[Pattern]:
        patterns: list[Pattern] = []
        for success in successes:
            sequence = success.action_sequence or _last_action_sequence(
                actions,
                self._max_sequence_length,
            )
            if not sequence:
                continue
            tools = success.tools or _tools_for_sequence(actions, sequence)
            signature = _signature("success", sequence, tools, _context_signature(success.context))
            patterns.append(
                Pattern(
                    kind=PatternKind.SUCCESS_SEQUENCE,
                    signature=signature,
                    description=f"Actions that led to {success.outcome}",
                    sequence=sequence,
                    tools=tools,
                    contexts=_context_items(success.context or session.context),
                    support=1,
                    confidence=_sequence_confidence(sequence, positive=True),
                    outcome=success.outcome,
                    session_ids=(session.session_id,),
                    metadata={"success_id": success.success_id},
                )
            )
        return patterns

    async def extract_failure_sequences(
        self,
        session: SessionSummary,
        failures: list[FailureRecord],
        actions: list[ActionRecord],
    ) -> list[Pattern]:
        patterns: list[Pattern] = []
        for failure in failures:
            sequence = failure.action_sequence or _last_action_sequence(
                actions,
                self._max_sequence_length,
            )
            if not sequence:
                continue
            tools = (failure.tool,) if failure.tool else _tools_for_sequence(actions, sequence)
            signature = _signature("failure", sequence, tools, _context_signature(failure.context))
            patterns.append(
                Pattern(
                    kind=PatternKind.FAILURE_SEQUENCE,
                    signature=signature,
                    description=f"Actions that led to {failure.failure_type}",
                    sequence=sequence,
                    tools=tools,
                    contexts=_context_items(failure.context or session.context),
                    support=1,
                    confidence=_sequence_confidence(sequence, positive=False),
                    outcome=failure.failure_type,
                    session_ids=(session.session_id,),
                    metadata={
                        "failure_id": failure.failure_id,
                        "severity": failure.severity,
                    },
                )
            )
        return patterns

    async def extract_tool_usage_patterns(
        self,
        session: SessionSummary,
        successes: list[SuccessRecord],
        failures: list[FailureRecord],
        actions: list[ActionRecord],
    ) -> list[Pattern]:
        tool_outcomes: dict[str, Counter[str]] = defaultdict(Counter)
        context_by_tool: dict[str, Counter[str]] = defaultdict(Counter)

        for action in actions:
            if action.tool is None:
                continue
            outcome = _action_outcome(action)
            tool_outcomes[action.tool][outcome] += 1
            for item in _context_items(action.metadata):
                context_by_tool[action.tool][item] += 1

        for success in successes:
            for tool in success.tools:
                tool_outcomes[tool]["success"] += 1
                for item in _context_items(success.context or session.context):
                    context_by_tool[tool][item] += 1

        for failure in failures:
            if failure.tool:
                tool_outcomes[failure.tool]["failure"] += 1
                for item in _context_items(failure.context or session.context):
                    context_by_tool[failure.tool][item] += 1

        patterns: list[Pattern] = []
        for tool, outcomes in sorted(tool_outcomes.items()):
            total = outcomes["success"] + outcomes["failure"] + outcomes["unknown"]
            if total == 0:
                continue
            success_rate = outcomes["success"] / total
            confidence = _bounded(0.35 + min(total, 8) * 0.06 + success_rate * 0.25)
            contexts = tuple(item for item, _ in context_by_tool[tool].most_common(5))
            patterns.append(
                Pattern(
                    kind=PatternKind.TOOL_USAGE,
                    signature=f"tool:{tool}",
                    description=f"Tool usage profile for {tool}",
                    tools=(tool,),
                    contexts=contexts,
                    support=total,
                    confidence=confidence,
                    outcome="success" if success_rate >= 0.5 else "failure",
                    session_ids=(session.session_id,),
                    metadata={
                        "successes": outcomes["success"],
                        "failures": outcomes["failure"],
                        "unknown": outcomes["unknown"],
                        "success_rate": success_rate,
                    },
                )
            )
        return patterns

    async def extract_context_patterns(
        self,
        session: SessionSummary,
        successes: list[SuccessRecord],
        failures: list[FailureRecord],
    ) -> list[Pattern]:
        outcomes: dict[str, Counter[str]] = defaultdict(Counter)
        for item in _context_items(session.context):
            outcomes[item]["success" if session.succeeded else "failure"] += 1
        for success in successes:
            for item in _context_items(success.context):
                outcomes[item]["success"] += 1
        for failure in failures:
            for item in _context_items(failure.context):
                outcomes[item]["failure"] += 1

        patterns: list[Pattern] = []
        for context_item, counts in sorted(outcomes.items()):
            total = counts["success"] + counts["failure"]
            if total == 0:
                continue
            success_rate = counts["success"] / total
            confidence = _bounded(0.4 + min(total, 6) * 0.05 + abs(success_rate - 0.5) * 0.3)
            patterns.append(
                Pattern(
                    kind=PatternKind.CONTEXT,
                    signature=f"context:{context_item}",
                    description=f"Outcome correlation for {context_item}",
                    contexts=(context_item,),
                    support=total,
                    confidence=confidence,
                    outcome="success" if success_rate >= 0.5 else "failure",
                    session_ids=(session.session_id,),
                    metadata={
                        "successes": counts["success"],
                        "failures": counts["failure"],
                        "success_rate": success_rate,
                    },
                )
            )
        return patterns

    async def extract_temporal_patterns(
        self,
        session: SessionSummary,
        successes: list[SuccessRecord],
        failures: list[FailureRecord],
    ) -> list[Pattern]:
        patterns: list[Pattern] = []
        outcome = "success" if session.succeeded or successes else "failure"
        if failures and not successes:
            outcome = "failure"

        hour_bucket = _hour_bucket(session.started_at)
        duration_bucket = _duration_bucket(session.duration_seconds)
        temporal_items = (f"hour={hour_bucket}", f"duration={duration_bucket}")
        patterns.append(
            Pattern(
                kind=PatternKind.TEMPORAL,
                signature=f"temporal:{hour_bucket}:{duration_bucket}",
                description="Temporal session outcome correlation",
                contexts=temporal_items,
                support=1,
                confidence=0.45,
                outcome=outcome,
                session_ids=(session.session_id,),
                metadata={
                    "started_at": session.started_at.isoformat(),
                    "duration_seconds": session.duration_seconds,
                },
            )
        )
        return patterns


def _actions_from_session(session: SessionSummary) -> list[ActionRecord]:
    actions = list(session.actions)
    for event in session.events:
        action = _action_from_event(event)
        if action is not None:
            actions.append(action)
    return sorted(actions, key=lambda item: item.timestamp or datetime.min.replace(tzinfo=UTC))


def _failures_from_session(
    session: SessionSummary,
    actions: list[ActionRecord],
) -> list[FailureRecord]:
    failures = list(session.failures)
    for event in session.events:
        failure = _failure_from_event(session, event, actions)
        if failure is not None:
            failures.append(failure)
    if not failures and not session.succeeded:
        failures.append(
            FailureRecord(
                session_id=session.session_id,
                failure_type=str(session.metadata.get("failure_type", "session_failed")),
                message=str(session.metadata.get("error", "")),
                action_sequence=_last_action_sequence(actions, MAX_SEQUENCE_LENGTH),
                context=session.context,
                severity=float(session.metadata.get("severity", 1.0)),
                timestamp=session.ended_at or session.started_at,
            )
        )
    return failures


def _successes_from_session(
    session: SessionSummary,
    actions: list[ActionRecord],
) -> list[SuccessRecord]:
    successes = list(session.successes)
    for event in session.events:
        success = _success_from_event(session, event, actions)
        if success is not None:
            successes.append(success)
    if not successes and session.succeeded:
        successes.append(
            SuccessRecord(
                session_id=session.session_id,
                outcome=str(session.metadata.get("outcome", "session_completed")),
                action_sequence=_last_action_sequence(actions, MAX_SEQUENCE_LENGTH),
                tools=_all_tools(actions),
                context=session.context,
                duration_seconds=session.duration_seconds,
                timestamp=session.ended_at or session.started_at,
            )
        )
    return successes


def _action_from_event(event: dict[str, Any]) -> ActionRecord | None:
    event_type = str(event.get("type") or event.get("event_type") or "")
    payload = _payload(event)
    action = payload.get("action") or payload.get("command") or payload.get("name")
    if not action and not event_type.endswith((".started", ".completed", ".failed")):
        return None
    if not action:
        action = event_type.rsplit(".", 1)[-1]
    tool = payload.get("tool") or payload.get("adapter") or payload.get("capability")
    success = _event_success(event_type, payload)
    return ActionRecord(
        action=str(action),
        tool=str(tool) if tool else None,
        success=success,
        duration_seconds=_optional_float(payload.get("duration_seconds")),
        timestamp=event.get("ts") or event.get("timestamp"),
        metadata={key: value for key, value in payload.items() if key not in {"secret", "token"}},
    )


def _failure_from_event(
    session: SessionSummary,
    event: dict[str, Any],
    actions: list[ActionRecord],
) -> FailureRecord | None:
    event_type = str(event.get("type") or event.get("event_type") or "")
    payload = _payload(event)
    is_failure_event = (
        "fail" in event_type
        or "error" in event_type
        or payload.get("success") is False
    )
    if not is_failure_event:
        return None
    failure_type = payload.get("failure_type") or payload.get("failure_class") or event_type
    return FailureRecord(
        session_id=session.session_id,
        failure_type=str(failure_type),
        message=str(payload.get("message") or payload.get("error") or ""),
        action_sequence=_last_action_sequence(actions, MAX_SEQUENCE_LENGTH),
        tool=str(payload["tool"]) if payload.get("tool") else None,
        context=_context_from_payload(session.context, payload),
        severity=_bounded(float(payload.get("severity", 1.0))),
        timestamp=(
            event.get("ts")
            or event.get("timestamp")
            or session.ended_at
            or session.started_at
        ),
    )


def _success_from_event(
    session: SessionSummary,
    event: dict[str, Any],
    actions: list[ActionRecord],
) -> SuccessRecord | None:
    event_type = str(event.get("type") or event.get("event_type") or "")
    payload = _payload(event)
    success_signal = (
        event_type.endswith((".completed", ".succeeded"))
        or "success" in event_type
        or payload.get("success") is True
    )
    if not success_signal:
        return None
    return SuccessRecord(
        session_id=session.session_id,
        outcome=str(payload.get("outcome") or payload.get("status") or event_type),
        action_sequence=_last_action_sequence(actions, MAX_SEQUENCE_LENGTH),
        tools=_all_tools(actions),
        context=_context_from_payload(session.context, payload),
        duration_seconds=_optional_float(payload.get("duration_seconds")),
        timestamp=(
            event.get("ts")
            or event.get("timestamp")
            or session.ended_at
            or session.started_at
        ),
    )


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload", {})
    return payload if isinstance(payload, dict) else {}


def _event_success(event_type: str, payload: dict[str, Any]) -> bool | None:
    if isinstance(payload.get("success"), bool):
        return bool(payload["success"])
    if event_type.endswith((".completed", ".succeeded")) or "success" in event_type:
        return True
    if "fail" in event_type or "error" in event_type:
        return False
    return None


def _last_action_sequence(
    actions: list[ActionRecord],
    max_length: int,
) -> tuple[str, ...]:
    return tuple(action.action for action in actions[-max_length:])


def _tools_for_sequence(
    actions: list[ActionRecord],
    sequence: Iterable[str],
) -> tuple[str, ...]:
    wanted = list(sequence)
    tools: list[str] = []
    for action in actions:
        if action.action in wanted and action.tool:
            tools.append(action.tool)
    return tuple(dict.fromkeys(tools))


def _all_tools(actions: list[ActionRecord]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(action.tool for action in actions if action.tool))


def _action_outcome(action: ActionRecord) -> str:
    if action.success is True:
        return "success"
    if action.success is False:
        return "failure"
    return "unknown"


def _context_from_payload(
    session_context: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    context = dict(session_context)
    payload_context = payload.get("context")
    if isinstance(payload_context, dict):
        context.update(payload_context)
    for key in ("domain", "task_type", "language", "risk_tier", "package"):
        if key in payload:
            context[key] = payload[key]
    return context


def _context_items(context: dict[str, Any]) -> tuple[str, ...]:
    items: list[str] = []
    for key, value in sorted(context.items()):
        if value is None or isinstance(value, (dict, list, tuple, set)):
            continue
        text = str(value).strip()
        if text:
            items.append(f"{key}={text}")
    return tuple(items)


def _context_signature(context: dict[str, Any]) -> str:
    return ",".join(_context_items(context)[:4])


def _signature(
    prefix: str,
    sequence: Iterable[str],
    tools: Iterable[str],
    context_signature: str,
) -> str:
    parts = [
        prefix,
        ">".join(sequence),
        ",".join(tools),
        context_signature,
    ]
    return "|".join(part for part in parts if part)


def _sequence_confidence(sequence: tuple[str, ...], *, positive: bool) -> float:
    base = 0.48 if positive else 0.52
    return _bounded(base + min(len(sequence), MAX_SEQUENCE_LENGTH) * 0.04)


def _hour_bucket(started_at: datetime) -> str:
    hour = started_at.hour
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"


def _duration_bucket(duration_seconds: float | None) -> str:
    if duration_seconds is None:
        return "unknown"
    if duration_seconds < 300:
        return "short"
    if duration_seconds < 1800:
        return "medium"
    return "long"


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return max(float(value), 0.0)
    except (TypeError, ValueError):
        return None


def _bounded(value: float) -> float:
    return max(0.0, min(value, 1.0))
