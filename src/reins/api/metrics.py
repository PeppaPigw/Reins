from __future__ import annotations

import time
from dataclasses import dataclass, field


_HISTOGRAM_BUCKETS = (0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 300.0)


@dataclass
class _Histogram:
    buckets: tuple[float, ...] = _HISTOGRAM_BUCKETS
    counts: dict[float, int] = field(
        default_factory=lambda: {bucket: 0 for bucket in _HISTOGRAM_BUCKETS}
    )
    infinite_count: int = 0
    count: int = 0
    total: float = 0.0

    def observe(self, value: float) -> None:
        self.count += 1
        self.total += value
        matched = False
        for bucket in self.buckets:
            if value <= bucket:
                self.counts[bucket] += 1
                matched = True
        if not matched:
            self.infinite_count += 1


class MetricsCollector:
    """Collects and exposes operational metrics."""

    def __init__(self) -> None:
        self.started_at = time.monotonic()
        self.agents_total = 0
        self.agents_active = 0
        self.jobs_total = 0
        self.jobs_completed = 0
        self.jobs_failed = 0
        self.policy_evaluations_total = 0
        self.policy_denials_total = 0
        self.events_total = 0
        self.stream_connections = 0
        self.job_duration_seconds = _Histogram()

    def set_agents(self, *, total: int, active: int) -> None:
        self.agents_total = total
        self.agents_active = active

    def set_stream_connections(self, total: int) -> None:
        self.stream_connections = total

    def record_job_submitted(self) -> None:
        self.jobs_total += 1

    def record_job_completed(self, duration_seconds: float) -> None:
        self.jobs_completed += 1
        self.job_duration_seconds.observe(duration_seconds)

    def record_job_failed(self, duration_seconds: float) -> None:
        self.jobs_failed += 1
        self.job_duration_seconds.observe(duration_seconds)

    def record_policy_evaluation(self, *, denied: bool) -> None:
        self.policy_evaluations_total += 1
        if denied:
            self.policy_denials_total += 1

    def record_event(self) -> None:
        self.events_total += 1

    def snapshot(self) -> dict[str, float | int]:
        elapsed_seconds = max(time.monotonic() - self.started_at, 0.001)
        terminal_jobs = self.jobs_completed + self.jobs_failed
        return {
            "reins_agents_total": self.agents_total,
            "reins_agents_active": self.agents_active,
            "reins_jobs_total": self.jobs_total,
            "reins_jobs_completed": self.jobs_completed,
            "reins_jobs_failed": self.jobs_failed,
            "reins_policy_evaluations_total": self.policy_evaluations_total,
            "reins_policy_denials_total": self.policy_denials_total,
            "reins_events_total": self.events_total,
            "reins_stream_connections": self.stream_connections,
            "job_throughput_per_minute": self.jobs_total / elapsed_seconds * 60,
            "error_rate": self.jobs_failed / terminal_jobs if terminal_jobs else 0.0,
        }

    def render_prometheus(self) -> str:
        lines = [
            "# HELP reins_agents_total Total registered agents.",
            "# TYPE reins_agents_total gauge",
            f"reins_agents_total {self.agents_total}",
            "# HELP reins_agents_active Currently active agents.",
            "# TYPE reins_agents_active gauge",
            f"reins_agents_active {self.agents_active}",
            "# HELP reins_jobs_total Total jobs submitted.",
            "# TYPE reins_jobs_total counter",
            f"reins_jobs_total {self.jobs_total}",
            "# HELP reins_jobs_completed Completed jobs.",
            "# TYPE reins_jobs_completed counter",
            f"reins_jobs_completed {self.jobs_completed}",
            "# HELP reins_jobs_failed Failed jobs.",
            "# TYPE reins_jobs_failed counter",
            f"reins_jobs_failed {self.jobs_failed}",
            "# HELP reins_job_duration_seconds Job execution time.",
            "# TYPE reins_job_duration_seconds histogram",
        ]

        histogram = self.job_duration_seconds
        cumulative = 0
        for bucket in histogram.buckets:
            cumulative = histogram.counts[bucket]
            lines.append(f'reins_job_duration_seconds_bucket{{le="{bucket:g}"}} {cumulative}')
        lines.append(f'reins_job_duration_seconds_bucket{{le="+Inf"}} {histogram.count}')
        lines.extend(
            [
                f"reins_job_duration_seconds_count {histogram.count}",
                f"reins_job_duration_seconds_sum {histogram.total:g}",
                "# HELP reins_policy_evaluations_total Policy evaluations.",
                "# TYPE reins_policy_evaluations_total counter",
                f"reins_policy_evaluations_total {self.policy_evaluations_total}",
                "# HELP reins_policy_denials_total Policy denials.",
                "# TYPE reins_policy_denials_total counter",
                f"reins_policy_denials_total {self.policy_denials_total}",
                "# HELP reins_events_total Total events emitted.",
                "# TYPE reins_events_total counter",
                f"reins_events_total {self.events_total}",
                "# HELP reins_stream_connections Active SSE connections.",
                "# TYPE reins_stream_connections gauge",
                f"reins_stream_connections {self.stream_connections}",
                "",
            ]
        )
        return "\n".join(lines)
