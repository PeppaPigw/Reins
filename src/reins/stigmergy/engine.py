from __future__ import annotations

import time
from collections import defaultdict

from reins.stigmergy.types import (
    DecayModel,
    StigmergyStats,
    Trace,
    TraceKind,
    TraceQuery,
)


class StigmergyEngine:
    """Indirect coordination through environmental traces.

    Agents deposit traces (like pheromones) at locations that influence
    other agents' decisions. Traces decay over time, creating dynamic
    coordination without direct communication.
    """

    def __init__(self, decay_model: DecayModel = DecayModel.EXPONENTIAL,
                 decay_rate: float = 0.1,
                 evaporation_threshold: float = 0.01,
                 reinforcement_factor: float = 1.5) -> None:
        self._decay_model = decay_model
        self._decay_rate = decay_rate
        self._evaporation_threshold = evaporation_threshold
        self._reinforcement_factor = reinforcement_factor
        self._traces: dict[str, Trace] = {}
        self._location_index: dict[str, list[str]] = defaultdict(list)
        self._evaporated_count = 0
        self._last_decay_time = time.monotonic()

    def deposit(self, agent_id: str, kind: TraceKind, location: str,
                intensity: float = 1.0,
                payload: dict | None = None) -> Trace:
        existing = self._find_matching(agent_id, kind, location)
        if existing:
            new_intensity = min(
                existing.intensity * self._reinforcement_factor,
                existing.intensity + intensity,
            )
            updated = Trace(
                trace_id=existing.trace_id, agent_id=existing.agent_id,
                kind=existing.kind, location=existing.location,
                intensity=new_intensity,
                payload={**existing.payload, **(payload or {})},
                deposited_at=existing.deposited_at,
            )
            self._traces[existing.trace_id] = updated
            return updated

        trace = Trace(
            agent_id=agent_id, kind=kind, location=location,
            intensity=intensity, payload=payload or {},
        )
        self._traces[trace.trace_id] = trace
        self._location_index[location].append(trace.trace_id)
        return trace

    def sense(self, location: str, kind: TraceKind | None = None,
              min_intensity: float = 0.0) -> list[Trace]:
        trace_ids = self._location_index.get(location, [])
        results = []
        for tid in trace_ids:
            trace = self._traces.get(tid)
            if not trace:
                continue
            if trace.intensity < min_intensity:
                continue
            if kind and trace.kind != kind:
                continue
            results.append(trace)
        return sorted(results, key=lambda t: -t.intensity)

    def sense_nearby(self, location: str, radius: int = 1) -> list[Trace]:
        results = []
        for loc, tids in self._location_index.items():
            if self._location_distance(location, loc) <= radius:
                for tid in tids:
                    trace = self._traces.get(tid)
                    if trace and trace.intensity >= self._evaporation_threshold:
                        results.append(trace)
        return sorted(results, key=lambda t: -t.intensity)

    def get_intensity_at(self, location: str, kind: TraceKind | None = None) -> float:
        traces = self.sense(location, kind=kind)
        return sum(t.intensity for t in traces)

    def get_gradient(self, locations: list[str], kind: TraceKind | None = None) -> list[tuple[str, float]]:
        scored = [(loc, self.get_intensity_at(loc, kind)) for loc in locations]
        return sorted(scored, key=lambda x: -x[1])

    def decay(self, elapsed_seconds: float = 1.0) -> int:
        evaporated = 0
        to_remove = []

        for tid, trace in self._traces.items():
            if self._decay_model == DecayModel.NONE:
                continue

            if self._decay_model == DecayModel.LINEAR:
                new_intensity = trace.intensity - self._decay_rate * elapsed_seconds
            elif self._decay_model == DecayModel.EXPONENTIAL:
                import math
                new_intensity = trace.intensity * math.exp(-self._decay_rate * elapsed_seconds)
            else:
                new_intensity = 0.0 if elapsed_seconds > (1.0 / self._decay_rate) else trace.intensity

            if new_intensity < self._evaporation_threshold:
                to_remove.append(tid)
                evaporated += 1
            else:
                updated = Trace(
                    trace_id=trace.trace_id, agent_id=trace.agent_id,
                    kind=trace.kind, location=trace.location,
                    intensity=new_intensity, payload=trace.payload,
                    deposited_at=trace.deposited_at,
                )
                self._traces[tid] = updated

        for tid in to_remove:
            trace = self._traces.pop(tid)
            if trace.location in self._location_index:
                self._location_index[trace.location] = [
                    t for t in self._location_index[trace.location] if t != tid
                ]

        self._evaporated_count += evaporated
        return evaporated

    def get_hotspots(self, top_n: int = 5) -> list[tuple[str, float]]:
        location_intensities: dict[str, float] = defaultdict(float)
        for trace in self._traces.values():
            location_intensities[trace.location] += trace.intensity
        sorted_locs = sorted(location_intensities.items(), key=lambda x: -x[1])
        return sorted_locs[:top_n]

    def get_stats(self) -> StigmergyStats:
        by_kind: dict[str, int] = defaultdict(int)
        intensities = []
        for trace in self._traces.values():
            by_kind[trace.kind.value] += 1
            intensities.append(trace.intensity)

        avg_intensity = sum(intensities) / len(intensities) if intensities else 0.0
        hotspots = tuple(loc for loc, _ in self.get_hotspots(3))

        return StigmergyStats(
            total_traces=len(self._traces) + self._evaporated_count,
            active_traces=len(self._traces),
            evaporated=self._evaporated_count,
            by_kind=dict(by_kind),
            avg_intensity=avg_intensity,
            hotspots=hotspots,
        )

    def _find_matching(self, agent_id: str, kind: TraceKind, location: str) -> Trace | None:
        for tid in self._location_index.get(location, []):
            trace = self._traces.get(tid)
            if trace and trace.agent_id == agent_id and trace.kind == kind:
                return trace
        return None

    def _location_distance(self, a: str, b: str) -> int:
        if a == b:
            return 0
        parts_a = a.split("/")
        parts_b = b.split("/")
        common = 0
        for pa, pb in zip(parts_a, parts_b):
            if pa == pb:
                common += 1
            else:
                break
        return (len(parts_a) - common) + (len(parts_b) - common)
