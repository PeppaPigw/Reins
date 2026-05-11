"""Tests for the performance benchmark framework."""

from __future__ import annotations

import time

import pytest

from reins.performance.benchmarks import (
    BenchmarkResult,
    ContextCompilationBenchmark,
    JournalAppendBenchmark,
    _percentile,
    benchmark,
    run_all_benchmarks,
    run_benchmark_function,
)


class TestBenchmarkResult:
    def test_benchmark_result_fields(self) -> None:
        result = BenchmarkResult(
            name="test",
            iterations=10,
            mean_ms=5.0,
            median_ms=4.5,
            p95_ms=8.0,
            p99_ms=9.5,
            min_ms=2.0,
            max_ms=10.0,
            passed=True,
            threshold_ms=20.0,
        )
        assert result.name == "test"
        assert result.iterations == 10
        assert result.mean_ms == 5.0
        assert result.median_ms == 4.5
        assert result.p95_ms == 8.0
        assert result.p99_ms == 9.5
        assert result.min_ms == 2.0
        assert result.max_ms == 10.0
        assert result.passed is True
        assert result.threshold_ms == 20.0

    def test_benchmark_result_no_threshold(self) -> None:
        result = BenchmarkResult(
            name="no_thresh",
            iterations=5,
            mean_ms=1.0,
            median_ms=1.0,
            p95_ms=1.0,
            p99_ms=1.0,
            min_ms=1.0,
            max_ms=1.0,
            passed=True,
        )
        assert result.threshold_ms is None


class TestBenchmarkFunction:
    def test_benchmark_function_measures_time(self) -> None:
        def slow_func() -> None:
            time.sleep(0.001)  # 1ms

        result = run_benchmark_function(slow_func, "slow_test", iterations=5)
        assert result.name == "slow_test"
        assert result.iterations == 5
        assert result.mean_ms > 0.5  # Should be at least ~1ms
        assert result.min_ms > 0.0

    def test_benchmark_passes_within_threshold(self) -> None:
        def fast_func() -> None:
            _ = 1 + 1

        result = run_benchmark_function(
            fast_func, "fast_test", iterations=10, threshold_ms=100.0
        )
        assert result.passed is True

    def test_benchmark_fails_above_threshold(self) -> None:
        def slow_func() -> None:
            time.sleep(0.01)  # 10ms

        result = run_benchmark_function(
            slow_func, "slow_test", iterations=5, threshold_ms=0.001
        )
        assert result.passed is False

    def test_benchmark_decorator(self) -> None:
        @benchmark("decorated", iterations=5, threshold_ms=1000.0)
        def my_func() -> None:
            _ = sum(range(100))

        result = my_func()
        assert isinstance(result, BenchmarkResult)
        assert result.name == "decorated"
        assert result.iterations == 5
        assert result.passed is True

    def test_benchmark_statistics_correct(self) -> None:
        call_count = 0

        def counting_func() -> None:
            nonlocal call_count
            call_count += 1

        result = run_benchmark_function(counting_func, "count", iterations=20)
        assert call_count == 20
        assert result.iterations == 20
        # Statistical invariants
        assert result.min_ms <= result.mean_ms
        assert result.mean_ms <= result.max_ms
        assert result.min_ms <= result.median_ms <= result.max_ms
        assert result.p95_ms <= result.max_ms
        assert result.p99_ms <= result.max_ms


class TestContextCompilationBenchmark:
    def test_context_compilation_benchmark_setup(self) -> None:
        bench = ContextCompilationBenchmark(spec_count=5, token_budget=4000)
        bench.setup()
        assert bench._projection is not None
        assert bench._compiler is not None
        assert bench._projection.count_specs() == 5

    def test_context_compilation_benchmark_runs(self, tmp_path: object) -> None:
        bench = ContextCompilationBenchmark(spec_count=10, token_budget=4000)
        bench.setup()
        elapsed = bench.run_once()
        assert elapsed > 0.0

    def test_context_compilation_within_500ms(self, tmp_path: object) -> None:
        bench = ContextCompilationBenchmark(spec_count=20, token_budget=8000)
        result = bench.run_benchmark(iterations=10)
        assert result.name == "context_compilation"
        assert result.threshold_ms == 500.0
        assert result.passed is True
        assert result.mean_ms < 500.0


class TestJournalAppendBenchmark:
    def test_journal_append_benchmark_runs(self, tmp_path: object) -> None:
        from pathlib import Path

        bench = JournalAppendBenchmark(event_count=10)
        bench.setup(Path(str(tmp_path)))
        elapsed = bench.run_once()
        assert elapsed > 0.0

    def test_journal_append_benchmark_performance(self, tmp_path: object) -> None:
        from pathlib import Path

        bench = JournalAppendBenchmark(event_count=50)
        bench.setup(Path(str(tmp_path)))
        result = bench.run_benchmark(iterations=10)
        assert result.name == "journal_append"
        assert result.iterations == 10
        assert result.mean_ms > 0.0
        assert result.min_ms <= result.max_ms


class TestRunAllBenchmarks:
    def test_run_all_benchmarks(self, tmp_path: object) -> None:
        from pathlib import Path

        results = run_all_benchmarks(tmp_dir=Path(str(tmp_path)))
        assert len(results) == 2
        names = [r.name for r in results]
        assert "context_compilation" in names
        assert "journal_append" in names
        for r in results:
            assert r.iterations > 0
            assert r.mean_ms > 0.0


class TestPercentile:
    def test_percentile_basic(self) -> None:
        data = list(range(1, 101))  # 1 to 100
        assert _percentile(data, 50) == pytest.approx(50.5, abs=0.5)
        assert _percentile(data, 95) == pytest.approx(95.05, abs=1.0)
        assert _percentile(data, 99) == pytest.approx(99.01, abs=1.0)

    def test_percentile_empty(self) -> None:
        assert _percentile([], 50) == 0.0

    def test_percentile_single(self) -> None:
        assert _percentile([5.0], 50) == 5.0
        assert _percentile([5.0], 99) == 5.0
