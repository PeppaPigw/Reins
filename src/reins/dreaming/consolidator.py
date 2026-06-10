from __future__ import annotations

import asyncio
import json
import os
from collections import Counter, defaultdict
from dataclasses import is_dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiofiles  # type: ignore[import-untyped]
from pydantic import BaseModel

from reins.dreaming.patterns import PatternExtractor
from reins.dreaming.types import (
    DreamReport,
    FailureCluster,
    FailureRecord,
    HarnessOptimization,
    OptimizationType,
    Pattern,
    PatternKind,
    PruneResult,
    SessionSummary,
    Strategy,
    SuccessRecord,
)

STALE_MEMORY_DAYS = 90


class DreamConsolidator:
    """Cross-session learning consolidation engine.

    Runs asynchronously between sessions to:
    1. Extract patterns from completed sessions
    2. Cluster similar failures
    3. Identify successful strategies
    4. Update the harness configuration automatically
    5. Prune stale or contradicted memories
    """

    def __init__(
        self,
        pattern_extractor: PatternExtractor | None = None,
        *,
        store_path: Path | str | None = None,
        min_cluster_size: int = 1,
        stale_memory_days: int = STALE_MEMORY_DAYS,
    ) -> None:
        self._patterns = pattern_extractor or PatternExtractor()
        self._min_cluster_size = min_cluster_size
        self._stale_memory_days = stale_memory_days
        self._journal_path: Path | None = None
        if store_path is not None:
            path = Path(store_path)
            path.mkdir(parents=True, exist_ok=True)
            self._journal_path = path / "dream_journal.jsonl"
            self._journal_path.touch(exist_ok=True)

    async def consolidate(self, sessions: list[SessionSummary]) -> DreamReport:
        extracted: list[Pattern] = []
        failures: list[FailureRecord] = []
        successes: list[SuccessRecord] = []

        for session in sessions:
            extracted.extend(await self.extract_patterns(session))
            failures.extend(session.failures)
            successes.extend(session.successes)

        inferred_failures, inferred_successes = _records_from_patterns(extracted)
        failures.extend(inferred_failures)
        successes.extend(inferred_successes)

        patterns = _merge_patterns(extracted)
        clusters = await self.cluster_failures(failures)
        strategies = await self.identify_strategies(successes)
        report = DreamReport(
            session_ids=tuple(session.session_id for session in sessions),
            patterns=tuple(patterns),
            failure_clusters=tuple(clusters),
            strategies=tuple(strategies),
            metrics={
                "session_count": len(sessions),
                "pattern_count": len(patterns),
                "failure_count": len(failures),
                "success_count": len(successes),
            },
        )
        recommendations = await self.generate_recommendations(report)
        final_report = report.model_copy(update={"recommendations": tuple(recommendations)})
        await self._persist_report(final_report)
        return final_report

    async def extract_patterns(self, session: SessionSummary) -> list[Pattern]:
        return await self._patterns.extract(session)

    async def cluster_failures(self, failures: list[FailureRecord]) -> list[FailureCluster]:
        grouped: dict[str, list[FailureRecord]] = defaultdict(list)
        for failure in failures:
            grouped[_failure_cluster_signature(failure)].append(failure)

        clusters: list[FailureCluster] = []
        for signature, items in grouped.items():
            if len(items) < self._min_cluster_size:
                continue
            failure_type = Counter(item.failure_type for item in items).most_common(1)[0][0]
            tools = Counter(item.tool for item in items if item.tool)
            context = _common_context([item.context for item in items])
            severity = sum(item.severity for item in items) / len(items)
            confidence = min(0.35 + len(items) * 0.15 + severity * 0.2, 1.0)
            clusters.append(
                FailureCluster(
                    signature=signature,
                    failure_type=failure_type,
                    failures=tuple(items),
                    count=len(items),
                    representative_message=items[0].message,
                    common_tools=tuple(tool for tool, _ in tools.most_common(4)),
                    common_context=context,
                    severity=severity,
                    confidence=confidence,
                )
            )
        clusters.sort(key=lambda item: (item.count, item.severity, item.confidence), reverse=True)
        return clusters

    async def identify_strategies(self, successes: list[SuccessRecord]) -> list[Strategy]:
        grouped: dict[str, list[SuccessRecord]] = defaultdict(list)
        for success in successes:
            grouped[_strategy_signature(success)].append(success)

        strategies: list[Strategy] = []
        for signature, items in grouped.items():
            sequence_counter = Counter(item.action_sequence for item in items)
            tool_counter: Counter[str] = Counter()
            context_counter: Counter[str] = Counter()
            durations: list[float] = []
            for item in items:
                tool_counter.update(item.tools)
                context_counter.update(_context_items(item.context))
                if item.duration_seconds is not None:
                    durations.append(item.duration_seconds)

            sequence = sequence_counter.most_common(1)[0][0] if sequence_counter else ()
            average_duration = sum(durations) / len(durations) if durations else None
            confidence = min(0.4 + len(items) * 0.12 + min(len(tool_counter), 4) * 0.04, 1.0)
            strategies.append(
                Strategy(
                    name=f"strategy:{signature}",
                    action_sequence=sequence,
                    tools=tuple(tool for tool, _ in tool_counter.most_common(5)),
                    contexts=tuple(context for context, _ in context_counter.most_common(5)),
                    support=len(items),
                    success_rate=1.0,
                    confidence=confidence,
                    average_duration_seconds=average_duration,
                    rationale=f"Observed in {len(items)} successful session outcome(s)",
                )
            )
        strategies.sort(key=lambda item: (item.confidence, item.support), reverse=True)
        return strategies

    async def prune_memories(self, memories: list[Any], contradictions: list[Any]) -> PruneResult:
        contradiction_terms = {_memory_signature(item) for item in contradictions}
        now = datetime.now(UTC)
        pruned: list[str] = []
        retained: list[str] = []
        adjustments: dict[str, float] = {}
        reasons: dict[str, str] = {}

        for memory in memories:
            memory_id = _memory_id(memory)
            if not memory_id:
                continue
            confidence = _memory_confidence(memory)
            signature = _memory_signature(memory)
            created_at = _memory_created_at(memory)
            age_days = (now - created_at).days if created_at is not None else 0
            contradicted = signature in contradiction_terms and bool(signature)

            if contradicted or confidence <= 0.15 or age_days > self._stale_memory_days:
                pruned.append(memory_id)
                if contradicted:
                    reasons[memory_id] = "contradicted"
                elif confidence <= 0.15:
                    reasons[memory_id] = "low_confidence"
                else:
                    reasons[memory_id] = "stale"
                continue

            retained.append(memory_id)
            if confidence < 0.35:
                adjusted = max(confidence * 0.8, 0.1)
                adjustments[memory_id] = adjusted
                reasons[memory_id] = "confidence_decay"

        return PruneResult(
            pruned_ids=tuple(pruned),
            retained_ids=tuple(retained),
            confidence_adjustments=adjustments,
            reasons=reasons,
        )

    async def generate_recommendations(
        self,
        report: DreamReport,
    ) -> list[HarnessOptimization]:
        recommendations: list[HarnessOptimization] = []
        recommendations.extend(_context_recommendations(report))
        recommendations.extend(_tool_recommendations(report))
        recommendations.extend(_routing_recommendations(report))
        recommendations.extend(_policy_recommendations(report))
        recommendations.extend(_timeout_recommendations(report))
        recommendations.sort(key=lambda item: (item.confidence, item.expected_impact), reverse=True)
        return recommendations

    async def load_reports(self) -> list[DreamReport]:
        if self._journal_path is None:
            return []
        reports: list[DreamReport] = []
        async with aiofiles.open(self._journal_path, "r", encoding="utf-8") as handle:
            async for line in handle:
                if not line.strip():
                    continue
                event = json.loads(line)
                if event.get("event_type") == "dream.report.generated":
                    reports.append(DreamReport.model_validate(event["payload"]["report"]))
        return reports

    async def _persist_report(self, report: DreamReport) -> None:
        if self._journal_path is None:
            return
        event = {
            "event_type": "dream.report.generated",
            "timestamp": datetime.now(UTC).isoformat(),
            "payload": {"report": report.model_dump(mode="json")},
        }
        line = json.dumps(event, sort_keys=True) + "\n"
        async with aiofiles.open(self._journal_path, "a", encoding="utf-8") as handle:
            await handle.write(line)
            await handle.flush()
            await asyncio.to_thread(os.fsync, handle.fileno())


def _merge_patterns(patterns: list[Pattern]) -> list[Pattern]:
    grouped: dict[tuple[PatternKind, str], list[Pattern]] = defaultdict(list)
    for pattern in patterns:
        grouped[(pattern.kind, pattern.signature)].append(pattern)

    merged: list[Pattern] = []
    for (_, _), items in grouped.items():
        first = items[0]
        support = sum(item.support for item in items)
        confidence = min(
            sum(item.confidence * item.support for item in items) / support
            + min(len(items), 5) * 0.05,
            1.0,
        )
        sessions: list[str] = []
        tools: list[str] = []
        contexts: list[str] = []
        for item in items:
            sessions.extend(item.session_ids)
            tools.extend(item.tools)
            contexts.extend(item.contexts)
        merged.append(
            first.model_copy(
                update={
                    "support": support,
                    "confidence": confidence,
                    "session_ids": tuple(dict.fromkeys(sessions)),
                    "tools": tuple(dict.fromkeys(tools)),
                    "contexts": tuple(dict.fromkeys(contexts)),
                }
            )
        )
    merged.sort(key=lambda item: (item.confidence, item.support), reverse=True)
    return merged


def _records_from_patterns(
    patterns: list[Pattern],
) -> tuple[list[FailureRecord], list[SuccessRecord]]:
    failures: list[FailureRecord] = []
    successes: list[SuccessRecord] = []
    for pattern in patterns:
        session_id = pattern.session_ids[0] if pattern.session_ids else "unknown"
        if pattern.kind is PatternKind.FAILURE_SEQUENCE:
            failures.append(
                FailureRecord(
                    session_id=session_id,
                    failure_type=pattern.outcome or "failure",
                    action_sequence=pattern.sequence,
                    tool=pattern.tools[0] if pattern.tools else None,
                    context=_context_from_items(pattern.contexts),
                    severity=float(pattern.metadata.get("severity", 1.0)),
                )
            )
        elif pattern.kind is PatternKind.SUCCESS_SEQUENCE:
            successes.append(
                SuccessRecord(
                    session_id=session_id,
                    outcome=pattern.outcome or "success",
                    action_sequence=pattern.sequence,
                    tools=pattern.tools,
                    context=_context_from_items(pattern.contexts),
                )
            )
    return failures, successes


def _failure_cluster_signature(failure: FailureRecord) -> str:
    context_domain = str(failure.context.get("domain", "")).lower().strip()
    tool = (failure.tool or "").lower().strip()
    message_terms = tuple(_tokenize(failure.message)[:3])
    return "|".join(
        item
        for item in (
            failure.failure_type.lower().strip(),
            tool,
            context_domain,
            " ".join(message_terms),
        )
        if item
    )


def _strategy_signature(success: SuccessRecord) -> str:
    sequence = ">".join(success.action_sequence[-4:])
    tools = ",".join(success.tools[:4])
    domain = str(success.context.get("domain", "")).strip()
    return "|".join(item for item in (sequence, tools, domain) if item) or success.outcome


def _common_context(contexts: list[dict[str, Any]]) -> dict[str, Any]:
    if not contexts:
        return {}
    keys = set(contexts[0])
    for context in contexts[1:]:
        keys &= set(context)
    result: dict[str, Any] = {}
    for key in sorted(keys):
        values = {str(context.get(key)) for context in contexts}
        if len(values) == 1:
            result[key] = contexts[0][key]
    return result


def _context_items(context: dict[str, Any]) -> tuple[str, ...]:
    items: list[str] = []
    for key, value in sorted(context.items()):
        if value is None or isinstance(value, (dict, list, tuple, set)):
            continue
        text = str(value).strip()
        if text:
            items.append(f"{key}={text}")
    return tuple(items)


def _context_from_items(items: tuple[str, ...]) -> dict[str, Any]:
    context: dict[str, Any] = {}
    for item in items:
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        context[key] = value
    return context


def _context_recommendations(report: DreamReport) -> list[HarnessOptimization]:
    recommendations: list[HarnessOptimization] = []
    context_patterns = [
        pattern
        for pattern in report.patterns
        if (
            pattern.kind is PatternKind.CONTEXT
            and pattern.outcome == "success"
            and pattern.confidence >= 0.55
        )
    ]
    for pattern in context_patterns[:5]:
        recommendations.append(
            HarnessOptimization(
                optimization_type=OptimizationType.CONTEXT,
                target=pattern.contexts[0] if pattern.contexts else pattern.signature,
                change={"load_by_default": True, "priority_delta": 0.1},
                rationale=(
                    "Context correlated with successful outcomes across "
                    f"{pattern.support} signal(s)"
                ),
                confidence=pattern.confidence,
                expected_impact=min(pattern.confidence * 0.25, 0.2),
                evidence=pattern.session_ids,
            )
        )
    return recommendations


def _tool_recommendations(report: DreamReport) -> list[HarnessOptimization]:
    recommendations: list[HarnessOptimization] = []
    for pattern in report.patterns:
        if pattern.kind is not PatternKind.TOOL_USAGE or not pattern.tools:
            continue
        success_rate = float(pattern.metadata.get("success_rate", 0.0))
        if success_rate >= 0.65 and pattern.confidence >= 0.55:
            recommendations.append(
                HarnessOptimization(
                    optimization_type=OptimizationType.TOOL,
                    target=pattern.tools[0],
                    change={"preference_delta": 0.15, "prefer_for": pattern.contexts},
                    rationale=f"Tool succeeded in {success_rate:.0%} of observed outcomes",
                    confidence=pattern.confidence,
                    expected_impact=min(success_rate * 0.2, 0.2),
                    evidence=pattern.session_ids,
                )
            )
        elif success_rate <= 0.35 and pattern.support >= 2:
            recommendations.append(
                HarnessOptimization(
                    optimization_type=OptimizationType.TOOL,
                    target=pattern.tools[0],
                    change={"preference_delta": -0.15, "avoid_for": pattern.contexts},
                    rationale=f"Tool underperformed with {success_rate:.0%} observed success",
                    confidence=pattern.confidence,
                    expected_impact=0.12,
                    evidence=pattern.session_ids,
                )
            )
    return recommendations


def _routing_recommendations(report: DreamReport) -> list[HarnessOptimization]:
    recommendations: list[HarnessOptimization] = []
    for strategy in report.strategies[:5]:
        if strategy.confidence < 0.55 or not strategy.tools:
            continue
        recommendations.append(
            HarnessOptimization(
                optimization_type=OptimizationType.ROUTING,
                target=strategy.name,
                change={
                    "preferred_tools": strategy.tools,
                    "preferred_sequence": strategy.action_sequence,
                    "contexts": strategy.contexts,
                },
                rationale=strategy.rationale,
                confidence=strategy.confidence,
                expected_impact=min(strategy.confidence * 0.2, 0.18),
                evidence=(strategy.strategy_id,),
            )
        )
    return recommendations


def _policy_recommendations(report: DreamReport) -> list[HarnessOptimization]:
    recommendations: list[HarnessOptimization] = []
    for cluster in report.failure_clusters:
        if cluster.severity < 0.7 or cluster.count < 2:
            continue
        target = str(cluster.common_context.get("risk_tier", cluster.failure_type))
        recommendations.append(
            HarnessOptimization(
                optimization_type=OptimizationType.POLICY,
                target=target,
                change={"risk_threshold_delta": -0.05, "require_extra_check": True},
                rationale=f"Repeated severe failure cluster: {cluster.failure_type}",
                confidence=cluster.confidence,
                expected_impact=0.15,
                evidence=tuple(failure.failure_id for failure in cluster.failures),
            )
        )
    return recommendations


def _timeout_recommendations(report: DreamReport) -> list[HarnessOptimization]:
    durations = [
        strategy.average_duration_seconds
        for strategy in report.strategies
        if strategy.average_duration_seconds is not None and strategy.support >= 1
    ]
    if not durations:
        return []
    average = sum(durations) / len(durations)
    if average <= 0:
        return []
    return [
        HarnessOptimization(
            optimization_type=OptimizationType.TIMEOUT,
            target="default_session_timeout_seconds",
            change={"recommended_seconds": round(average * 1.5, 3)},
            rationale="Observed successful strategy durations support timeout tuning",
            confidence=min(0.45 + len(durations) * 0.1, 0.85),
            expected_impact=0.08,
            evidence=tuple(
                strategy.strategy_id
                for strategy in report.strategies
                if strategy.average_duration_seconds
            ),
        )
    ]


def _memory_id(memory: Any) -> str:
    return str(_get_attr(memory, "memory_id", _get_attr(memory, "id", "")) or "")


def _memory_confidence(memory: Any) -> float:
    value = _get_attr(memory, "confidence", 0.5)
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return 0.5


def _memory_signature(memory: Any) -> str:
    content = str(_get_attr(memory, "content", _get_attr(memory, "summary", ""))).lower()
    return " ".join(_tokenize(content)[:12])


def _memory_created_at(memory: Any) -> datetime | None:
    raw = _get_attr(memory, "created_at", None)
    if raw is None:
        context = _get_attr(memory, "context", {})
        if isinstance(context, dict):
            raw = context.get("created_at") or context.get("timestamp")
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.astimezone(UTC) if raw.tzinfo is not None else raw.replace(tzinfo=UTC)
    try:
        normalized = str(raw)
        normalized = normalized[:-1] + "+00:00" if normalized.endswith("Z") else normalized
        parsed = datetime.fromisoformat(normalized)
        return parsed.astimezone(UTC) if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    except ValueError:
        return datetime.now(UTC) - timedelta(days=STALE_MEMORY_DAYS + 1)


def _get_attr(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    if isinstance(item, BaseModel):
        return getattr(item, key, default)
    if is_dataclass(item):
        return getattr(item, key, default)
    return getattr(item, key, default)


def _tokenize(value: str) -> list[str]:
    return [
        token.strip(".,:;()[]{}'\"").lower()
        for token in value.split()
        if token.strip(".,:;()[]{}'\"")
    ]
