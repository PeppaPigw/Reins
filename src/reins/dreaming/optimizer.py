from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiofiles  # type: ignore[import-untyped]

from reins.dreaming.consolidator import DreamConsolidator
from reins.dreaming.types import (
    ApplyResult,
    DreamReport,
    HarnessOptimization,
    ImpactMetrics,
    Optimization,
    OptimizationStatus,
    OptimizationType,
    utc_now,
)

OPTIMIZATION_APPLIED = "dream.optimization.applied"
OPTIMIZATION_ROLLED_BACK = "dream.optimization.rolled_back"
IMPACT_RECORDED = "dream.optimization.impact_recorded"


class HarnessOptimizer:
    """Automatically optimizes harness configuration based on dreaming insights."""

    def __init__(
        self,
        store_path: Path | str,
        *,
        consolidator: DreamConsolidator | None = None,
        min_confidence: float = 0.55,
    ) -> None:
        self._store_path = Path(store_path)
        self._store_path.mkdir(parents=True, exist_ok=True)
        self._journal_path = self._store_path / "optimizer_journal.jsonl"
        self._journal_path.touch(exist_ok=True)
        self._config_path = self._store_path / "harness_config.json"
        self._lock = asyncio.Lock()
        self._consolidator = consolidator or DreamConsolidator()
        self._min_confidence = min_confidence
        self._optimizations: dict[str, Optimization] = {}
        self._previous_values: dict[str, Any] = {}
        self._impact_metrics: dict[str, list[ImpactMetrics]] = {}
        self._config = self._load_config()
        self._replay_sync()

    async def optimize(self, report: DreamReport) -> list[Optimization]:
        candidates = await self._consolidator.generate_recommendations(report)
        optimizations = [
            _optimization_from_candidate(candidate)
            for candidate in candidates
            if candidate.confidence >= self._min_confidence
        ]
        return _deduplicate_optimizations(optimizations)

    async def apply_optimization(self, opt: Optimization) -> ApplyResult:
        async with self._lock:
            current = self._get_config_value(opt.optimization_type, opt.target)
            new_value = self._compute_new_value(opt, current)
            applied = opt.model_copy(
                update={
                    "status": OptimizationStatus.APPLIED,
                    "applied_at": utc_now(),
                }
            )
            event = {
                "event_type": OPTIMIZATION_APPLIED,
                "timestamp": utc_now().isoformat(),
                "payload": {
                    "optimization": applied.model_dump(mode="json"),
                    "previous_value": current,
                    "new_value": new_value,
                },
            }
            await self._append_event(event)
            self._apply_event(event)
            await self._save_config()
            return ApplyResult(
                optimization_id=opt.optimization_id,
                applied=True,
                status=OptimizationStatus.APPLIED,
                previous_value=current,
                new_value=new_value,
                message="optimization applied",
            )

    async def rollback_optimization(self, opt_id: str) -> None:
        async with self._lock:
            opt = self._optimizations.get(opt_id)
            if opt is None:
                return
            previous = self._previous_values.get(opt_id)
            rolled_back = opt.model_copy(
                update={
                    "status": OptimizationStatus.ROLLED_BACK,
                    "rolled_back_at": utc_now(),
                }
            )
            event = {
                "event_type": OPTIMIZATION_ROLLED_BACK,
                "timestamp": utc_now().isoformat(),
                "payload": {
                    "optimization": rolled_back.model_dump(mode="json"),
                    "restored_value": previous,
                },
            }
            await self._append_event(event)
            self._apply_event(event)
            await self._save_config()

    async def measure_impact(self, opt_id: str) -> ImpactMetrics:
        async with self._lock:
            metrics = self._measure_from_config(opt_id)
            event = {
                "event_type": IMPACT_RECORDED,
                "timestamp": utc_now().isoformat(),
                "payload": {"metrics": metrics.model_dump(mode="json")},
            }
            await self._append_event(event)
            self._apply_event(event)
            return metrics

    def get_config(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._config, sort_keys=True))

    def get_optimization(self, opt_id: str) -> Optimization | None:
        return self._optimizations.get(opt_id)

    def impact_history(self, opt_id: str) -> list[ImpactMetrics]:
        return list(self._impact_metrics.get(opt_id, []))

    def _load_config(self) -> dict[str, Any]:
        if not self._config_path.exists():
            return _default_config()
        data = json.loads(self._config_path.read_text(encoding="utf-8"))
        config = _default_config()
        _deep_update(config, data)
        return config

    async def _save_config(self) -> None:
        payload = json.dumps(self._config, indent=2, sort_keys=True) + "\n"
        async with aiofiles.open(self._config_path, "w", encoding="utf-8") as handle:
            await handle.write(payload)
            await handle.flush()
            await asyncio.to_thread(os.fsync, handle.fileno())

    async def _append_event(self, event: dict[str, Any]) -> None:
        line = json.dumps(event, sort_keys=True) + "\n"
        async with aiofiles.open(self._journal_path, "a", encoding="utf-8") as handle:
            await handle.write(line)
            await handle.flush()
            await asyncio.to_thread(os.fsync, handle.fileno())

    def _replay_sync(self) -> None:
        for line in self._journal_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            self._apply_event(json.loads(line))

    def _apply_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("event_type")
        payload = event.get("payload", {})
        if event_type == OPTIMIZATION_APPLIED:
            opt = Optimization.model_validate(payload["optimization"])
            self._optimizations[opt.optimization_id] = opt
            self._previous_values[opt.optimization_id] = payload.get("previous_value")
            self._set_config_value(opt.optimization_type, opt.target, payload.get("new_value"))
        elif event_type == OPTIMIZATION_ROLLED_BACK:
            opt = Optimization.model_validate(payload["optimization"])
            self._optimizations[opt.optimization_id] = opt
            self._set_config_value(opt.optimization_type, opt.target, payload.get("restored_value"))
        elif event_type == IMPACT_RECORDED:
            metrics = ImpactMetrics.model_validate(payload["metrics"])
            self._impact_metrics.setdefault(metrics.optimization_id, []).append(metrics)

    def _get_config_value(self, optimization_type: OptimizationType, target: str) -> Any:
        section = self._section_for_type(optimization_type)
        return section.get(target)

    def _set_config_value(
        self,
        optimization_type: OptimizationType,
        target: str,
        value: Any,
    ) -> None:
        section = self._section_for_type(optimization_type)
        if value is None:
            section.pop(target, None)
        else:
            section[target] = value

    def _section_for_type(self, optimization_type: OptimizationType) -> dict[str, Any]:
        key = {
            OptimizationType.CONTEXT: "context",
            OptimizationType.POLICY: "policy",
            OptimizationType.ROUTING: "routing",
            OptimizationType.TOOL: "tools",
            OptimizationType.TIMEOUT: "timeouts",
        }[optimization_type]
        section = self._config.setdefault(key, {})
        if not isinstance(section, dict):
            section = {}
            self._config[key] = section
        return section

    def _compute_new_value(self, opt: Optimization, current: Any) -> Any:
        if opt.optimization_type is OptimizationType.CONTEXT:
            return _merge_dict(
                current,
                {
                    "load_by_default": bool(opt.change.get("load_by_default", True)),
                    "priority": _bounded(
                        _as_float(_get_dict_value(current, "priority"), 0.5)
                        + _as_float(opt.change.get("priority_delta"), 0.0)
                    ),
                    "confidence": opt.confidence,
                },
            )
        if opt.optimization_type is OptimizationType.POLICY:
            return _merge_dict(
                current,
                {
                    "risk_threshold": _bounded(
                        _as_float(_get_dict_value(current, "risk_threshold"), 0.5)
                        + _as_float(opt.change.get("risk_threshold_delta"), 0.0)
                    ),
                    "require_extra_check": bool(opt.change.get("require_extra_check", False)),
                    "confidence": opt.confidence,
                },
            )
        if opt.optimization_type is OptimizationType.ROUTING:
            return _merge_dict(
                current,
                {
                    "preferred_tools": list(opt.change.get("preferred_tools", ())),
                    "preferred_sequence": list(opt.change.get("preferred_sequence", ())),
                    "contexts": list(opt.change.get("contexts", ())),
                    "confidence": opt.confidence,
                },
            )
        if opt.optimization_type is OptimizationType.TOOL:
            return _merge_dict(
                current,
                {
                    "preference": _bounded(
                        _as_float(_get_dict_value(current, "preference"), 0.5)
                        + _as_float(opt.change.get("preference_delta"), 0.0)
                    ),
                    "prefer_for": list(opt.change.get("prefer_for", ())),
                    "avoid_for": list(opt.change.get("avoid_for", ())),
                    "confidence": opt.confidence,
                },
            )
        if opt.optimization_type is OptimizationType.TIMEOUT:
            recommended = _as_float(opt.change.get("recommended_seconds"), 0.0)
            return max(recommended, 1.0) if recommended else current
        return current

    def _measure_from_config(self, opt_id: str) -> ImpactMetrics:
        opt = self._optimizations.get(opt_id)
        history = self._impact_metrics.get(opt_id, [])
        baseline_success = None
        baseline_duration = None
        if isinstance(opt, Optimization):
            baseline_success = _as_optional_rate(opt.change.get("baseline_success_rate"))
            baseline_duration = _as_optional_positive(opt.change.get("baseline_duration_seconds"))

        current_success = _as_optional_rate(_metric_value(opt, "current_success_rate"))
        current_duration = _as_optional_positive(_metric_value(opt, "current_duration_seconds"))

        if current_success is None and baseline_success is not None:
            current_success = baseline_success + opt.expected_impact if opt else baseline_success
            current_success = _bounded(current_success)
        if current_duration is None and baseline_duration is not None and opt is not None:
            current_duration = max(baseline_duration * (1.0 - max(opt.expected_impact, 0.0)), 0.0)

        improvement = 0.0
        regression = False
        if baseline_success is not None and current_success is not None:
            improvement += current_success - baseline_success
            regression = current_success < baseline_success
        if baseline_duration is not None and current_duration is not None and baseline_duration > 0:
            improvement += (baseline_duration - current_duration) / baseline_duration
            regression = regression or current_duration > baseline_duration

        return ImpactMetrics(
            optimization_id=opt_id,
            sample_size=len(history) + 1,
            baseline_success_rate=baseline_success,
            current_success_rate=current_success,
            baseline_duration_seconds=baseline_duration,
            current_duration_seconds=current_duration,
            regression_detected=regression,
            improvement_score=max(-1.0, min(improvement, 1.0)),
            measured_at=datetime.now(UTC),
        )


def _optimization_from_candidate(candidate: HarnessOptimization) -> Optimization:
    data = candidate.model_dump(mode="python")
    return Optimization.model_validate(data)


def _deduplicate_optimizations(optimizations: list[Optimization]) -> list[Optimization]:
    best: dict[tuple[OptimizationType, str], Optimization] = {}
    for opt in optimizations:
        key = (opt.optimization_type, opt.target)
        existing = best.get(key)
        if existing is None or (opt.confidence, opt.expected_impact) > (
            existing.confidence,
            existing.expected_impact,
        ):
            best[key] = opt
    return sorted(
        best.values(),
        key=lambda item: (item.confidence, item.expected_impact),
        reverse=True,
    )


def _default_config() -> dict[str, Any]:
    return {
        "context": {},
        "policy": {},
        "routing": {},
        "tools": {},
        "timeouts": {},
    }


def _deep_update(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value


def _merge_dict(current: Any, updates: dict[str, Any]) -> dict[str, Any]:
    base = dict(current) if isinstance(current, dict) else {}
    base.update(updates)
    return base


def _get_dict_value(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else None


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_optional_rate(value: Any) -> float | None:
    if value is None:
        return None
    return _bounded(_as_float(value, 0.0))


def _as_optional_positive(value: Any) -> float | None:
    if value is None:
        return None
    return max(_as_float(value, 0.0), 0.0)


def _bounded(value: float) -> float:
    return max(0.0, min(value, 1.0))


def _metric_value(opt: Optimization | None, key: str) -> Any:
    if opt is None:
        return None
    metrics = opt.change.get("metrics")
    if isinstance(metrics, dict) and key in metrics:
        return metrics[key]
    return opt.change.get(key)
