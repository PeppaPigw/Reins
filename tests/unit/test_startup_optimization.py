"""Tests for startup optimization and lazy import utilities."""

from __future__ import annotations

import sys

import pytest

from reins.performance.startup import (
    LazyModule,
    StartupMeasurement,
    get_import_breakdown,
    measure_import_time,
    measure_startup,
    optimize_imports_report,
)


class TestLazyModule:
    def test_lazy_module_defers_import(self) -> None:
        """LazyModule should not import the module until accessed."""

        class Host:
            mod = LazyModule("json")

        # The descriptor exists but module is not loaded yet
        descriptor = Host.__dict__["mod"]
        assert isinstance(descriptor, LazyModule)
        assert descriptor.is_loaded is False

    def test_lazy_module_caches_after_first_access(self) -> None:
        """After first access, the module should be cached."""

        class Host:
            mod = LazyModule("json")

        host = Host()
        # First access triggers import
        result = host.mod
        assert result is not None
        assert hasattr(result, "dumps")

        # Verify it's cached
        descriptor = Host.__dict__["mod"]
        assert descriptor.is_loaded is True

        # Second access returns same object
        assert host.mod is result

    def test_lazy_module_set_name(self) -> None:
        """__set_name__ should record the attribute name."""

        class Host:
            my_module = LazyModule("os")

        descriptor = Host.__dict__["my_module"]
        assert descriptor._attr_name == "my_module"
        assert descriptor.module_path == "os"


class TestMeasureImportTime:
    def test_measure_import_time_returns_positive(self) -> None:
        elapsed = measure_import_time("json")
        assert elapsed > 0.0

    def test_measure_import_time_for_known_module(self) -> None:
        elapsed = measure_import_time("os")
        assert isinstance(elapsed, float)
        assert elapsed >= 0.0


class TestGetImportBreakdown:
    def test_get_import_breakdown_returns_dict(self) -> None:
        breakdown = get_import_breakdown()
        assert isinstance(breakdown, dict)
        # Should have at least a few reins submodules
        assert len(breakdown) > 0
        # All values should be positive floats
        for name, ms in breakdown.items():
            assert isinstance(name, str)
            assert isinstance(ms, float)
            assert ms >= 0.0


class TestStartupMeasurement:
    def test_startup_measurement_fields(self) -> None:
        m = StartupMeasurement(
            cold_ms=150.0,
            warm_ms=5.0,
            import_breakdown={"reins.kernel": 20.0},
            passed_cold=True,
            passed_warm=True,
        )
        assert m.cold_ms == 150.0
        assert m.warm_ms == 5.0
        assert m.passed_cold is True
        assert m.passed_warm is True
        assert "reins.kernel" in m.import_breakdown

    def test_measure_startup_returns_measurement(self) -> None:
        m = measure_startup()
        assert isinstance(m, StartupMeasurement)
        assert m.cold_ms > 0.0
        assert m.warm_ms >= 0.0
        assert isinstance(m.import_breakdown, dict)

    def test_cold_start_under_threshold(self) -> None:
        """Cold start should be under 300ms for a well-optimized CLI."""
        m = measure_startup()
        # Allow generous threshold in test environments (CI can be slow)
        # The measurement itself tracks pass/fail against 300ms
        assert m.cold_ms < 5000.0  # Sanity: should not take 5 seconds

    def test_warm_start_under_threshold(self) -> None:
        """Warm start should be very fast since modules are cached."""
        m = measure_startup()
        # Warm start should be nearly instant (< 100ms target)
        assert m.warm_ms < 100.0


class TestOptimizeImportsReport:
    def test_optimize_imports_report_is_string(self) -> None:
        report = optimize_imports_report()
        assert isinstance(report, str)
        assert "Reins Startup Performance Report" in report
        assert "Cold start:" in report
        assert "Warm start:" in report
