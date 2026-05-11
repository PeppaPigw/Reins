"""Performance benchmark framework for Reins.

Provides timing-based benchmarks with statistical analysis and threshold assertions.
Benchmarks are repeatable and suitable for CI execution.
"""

from __future__ import annotations

import asyncio
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from reins.context.compiler_v2 import ContextCompilerV2
from reins.context.spec_projection import ContextSpecProjection, ResolvedSpec, SpecQuery
from reins.context.token_budget import TokenBudget
from reins.kernel.event.envelope import EventEnvelope
from reins.kernel.event.journal import EventJournal
from reins.kernel.types import Actor


@dataclass(frozen=True)
class BenchmarkResult:
    """Statistical result of a benchmark run."""

    name: str
    iterations: int
    mean_ms: float
    median_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    passed: bool
    threshold_ms: float | None = None


def _percentile(data: list[float], pct: float) -> float:
    """Calculate percentile from sorted data."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = (pct / 100.0) * (len(sorted_data) - 1)
    lower = int(idx)
    upper = lower + 1
    if upper >= len(sorted_data):
        return sorted_data[-1]
    weight = idx - lower
    return sorted_data[lower] * (1 - weight) + sorted_data[upper] * weight


def benchmark(
    name: str,
    iterations: int = 100,
    threshold_ms: float | None = None,
) -> Callable[[Callable[[], Any]], Callable[[], BenchmarkResult]]:
    """Decorator that turns a function into a benchmark.

    The decorated function is called `iterations` times and timing statistics
    are collected. Returns a BenchmarkResult with mean, median, p95, p99.

    Args:
        name: Human-readable benchmark name.
        iterations: Number of times to run the function.
        threshold_ms: Optional threshold — benchmark passes if mean < threshold.

    Returns:
        Decorator that wraps the function into a benchmark runner.
    """

    def decorator(func: Callable[[], Any]) -> Callable[[], BenchmarkResult]:
        def runner() -> BenchmarkResult:
            return run_benchmark_function(func, name, iterations, threshold_ms)

        runner.__name__ = f"benchmark_{name}"
        runner.__doc__ = f"Benchmark: {name}"
        return runner

    return decorator


def run_benchmark_function(
    func: Callable[[], Any],
    name: str,
    iterations: int = 100,
    threshold_ms: float | None = None,
) -> BenchmarkResult:
    """Run a callable as a benchmark and return statistical results.

    Args:
        func: Zero-argument callable to benchmark.
        name: Benchmark name.
        iterations: Number of iterations.
        threshold_ms: Optional pass/fail threshold on mean time.

    Returns:
        BenchmarkResult with timing statistics.
    """
    timings: list[float] = []

    for _ in range(iterations):
        start = time.perf_counter()
        func()
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        timings.append(elapsed_ms)

    mean_ms = statistics.mean(timings)
    median_ms = statistics.median(timings)
    p95_ms = _percentile(timings, 95)
    p99_ms = _percentile(timings, 99)
    min_ms = min(timings)
    max_ms = max(timings)

    passed = threshold_ms is None or mean_ms < threshold_ms

    return BenchmarkResult(
        name=name,
        iterations=iterations,
        mean_ms=mean_ms,
        median_ms=median_ms,
        p95_ms=p95_ms,
        p99_ms=p99_ms,
        min_ms=min_ms,
        max_ms=max_ms,
        passed=passed,
        threshold_ms=threshold_ms,
    )


class ContextCompilationBenchmark:
    """Benchmark for context compilation performance.

    Measures how long ContextCompilerV2.seed_context takes with a configurable
    number of specs and token budget. Threshold: <500ms mean.
    """

    THRESHOLD_MS = 500.0

    def __init__(self, spec_count: int = 20, token_budget: int = 8000) -> None:
        self._spec_count = spec_count
        self._token_budget = token_budget
        self._projection: ContextSpecProjection | None = None
        self._compiler: ContextCompilerV2 | None = None

    def setup(self) -> None:
        """Create mock specs and projection for benchmarking."""
        self._projection = ContextSpecProjection()

        # Register mock specs directly into the projection's internal state
        for i in range(self._spec_count):
            spec_type = "standing_law" if i % 3 == 0 else "task_contract"
            content = f"Spec {i} content. " * 50  # ~200 chars each
            event = EventEnvelope(
                run_id="bench-run",
                actor=Actor.runtime,
                type="spec.registered",
                payload={
                    "spec_id": f"spec-{i:03d}",
                    "spec_type": spec_type,
                    "scope": "workspace",
                    "applicability": {},
                    "required_capabilities": [],
                    "visibility_tier": 1,
                    "precedence": self._spec_count - i,
                    "source_path": None,
                    "registered_by": "benchmark",
                    "token_count": len(content) // 4,
                    "content": content,
                },
            )
            self._projection.apply_event(event)

        self._compiler = ContextCompilerV2(self._projection)

    def run_once(self) -> float:
        """Run one context compilation and return elapsed time in ms."""
        if self._compiler is None:
            raise RuntimeError("Call setup() before run_once()")

        budget = TokenBudget.default(total=self._token_budget)
        start = time.perf_counter()
        self._compiler.seed_context(
            task_state={"task_type": "backend"},
            granted_capabilities=set(),
            token_budget=budget,
            scope="workspace",
        )
        return (time.perf_counter() - start) * 1000.0

    def run_benchmark(self, iterations: int = 50) -> BenchmarkResult:
        """Run the full benchmark with statistical analysis.

        Args:
            iterations: Number of compilation iterations.

        Returns:
            BenchmarkResult with threshold=500ms.
        """
        self.setup()
        timings = [self.run_once() for _ in range(iterations)]

        mean_ms = statistics.mean(timings)
        median_ms = statistics.median(timings)
        p95_ms = _percentile(timings, 95)
        p99_ms = _percentile(timings, 99)

        return BenchmarkResult(
            name="context_compilation",
            iterations=iterations,
            mean_ms=mean_ms,
            median_ms=median_ms,
            p95_ms=p95_ms,
            p99_ms=p99_ms,
            min_ms=min(timings),
            max_ms=max(timings),
            passed=mean_ms < self.THRESHOLD_MS,
            threshold_ms=self.THRESHOLD_MS,
        )


class JournalAppendBenchmark:
    """Benchmark for event journal append performance.

    Measures how long EventJournal.append takes for individual events.
    Uses async execution via asyncio.run for each iteration.
    """

    THRESHOLD_MS = 50.0

    def __init__(self, event_count: int = 100) -> None:
        self._event_count = event_count
        self._journal: EventJournal | None = None
        self._tmp_dir: Path | None = None
        self._append_counter: int = 0

    def setup(self, tmp_dir: Path) -> None:
        """Create a journal in the given temporary directory."""
        self._tmp_dir = tmp_dir
        journal_path = tmp_dir / "bench_journal.jsonl"
        self._journal = EventJournal(journal_path)
        self._append_counter = 0

    def _make_event(self) -> EventEnvelope:
        """Create a test event for appending."""
        self._append_counter += 1
        return EventEnvelope(
            run_id="bench-run",
            actor=Actor.runtime,
            type="benchmark.event",
            payload={"counter": self._append_counter, "data": "x" * 100},
        )

    def run_once(self) -> float:
        """Append one event and return elapsed time in ms."""
        if self._journal is None:
            raise RuntimeError("Call setup(tmp_dir) before run_once()")

        event = self._make_event()
        start = time.perf_counter()
        asyncio.run(self._journal.append(event))
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return elapsed_ms

    def run_benchmark(self, iterations: int = 100) -> BenchmarkResult:
        """Run the full journal append benchmark.

        Note: setup(tmp_dir) must be called before this method.

        Args:
            iterations: Number of append iterations.

        Returns:
            BenchmarkResult with timing statistics.
        """
        if self._journal is None:
            raise RuntimeError("Call setup(tmp_dir) before run_benchmark()")

        timings = [self.run_once() for _ in range(iterations)]

        mean_ms = statistics.mean(timings)
        median_ms = statistics.median(timings)
        p95_ms = _percentile(timings, 95)
        p99_ms = _percentile(timings, 99)

        return BenchmarkResult(
            name="journal_append",
            iterations=iterations,
            mean_ms=mean_ms,
            median_ms=median_ms,
            p95_ms=p95_ms,
            p99_ms=p99_ms,
            min_ms=min(timings),
            max_ms=max(timings),
            passed=mean_ms < self.THRESHOLD_MS,
            threshold_ms=self.THRESHOLD_MS,
        )


def run_all_benchmarks(tmp_dir: Path | None = None) -> list[BenchmarkResult]:
    """Run all registered benchmarks and return results.

    Args:
        tmp_dir: Temporary directory for I/O benchmarks. If None, uses a
                 temporary directory created via tempfile.

    Returns:
        List of BenchmarkResult for each benchmark.
    """
    import tempfile

    results: list[BenchmarkResult] = []

    # Context compilation benchmark
    ctx_bench = ContextCompilationBenchmark()
    results.append(ctx_bench.run_benchmark(iterations=20))

    # Journal append benchmark
    if tmp_dir is None:
        tmp_dir = Path(tempfile.mkdtemp(prefix="reins_bench_"))

    journal_bench = JournalAppendBenchmark()
    journal_bench.setup(tmp_dir)
    results.append(journal_bench.run_benchmark(iterations=20))

    return results
