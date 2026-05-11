"""Startup time measurement and lazy import optimization utilities.

Provides tools to measure CLI cold/warm startup times, profile import overhead,
and defer expensive imports via the LazyModule descriptor.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
import time
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any


@dataclass(frozen=True)
class StartupMeasurement:
    """Result of CLI startup time measurement."""

    cold_ms: float
    """Cold start time (fresh subprocess import)."""

    warm_ms: float
    """Warm start time (in-process re-import)."""

    import_breakdown: dict[str, float]
    """Module name -> import time in ms (sorted slowest first)."""

    passed_cold: bool
    """True if cold start < 300ms."""

    passed_warm: bool
    """True if warm start < 100ms."""

    COLD_THRESHOLD_MS: float = field(default=300.0, repr=False)
    WARM_THRESHOLD_MS: float = field(default=100.0, repr=False)


class LazyModule:
    """Descriptor that defers module import until first attribute access.

    Use as a class-level descriptor to avoid importing heavy modules at
    class definition time. The module is imported on first access and cached.

    Example:
        class MyService:
            _heavy = LazyModule("some.heavy.module")

            def do_work(self):
                return self._heavy.some_function()
    """

    def __init__(self, module_path: str) -> None:
        self._module_path = module_path
        self._attr_name: str = ""
        self._module: ModuleType | None = None

    def __set_name__(self, owner: type, name: str) -> None:
        self._attr_name = name

    def __get__(self, obj: Any, objtype: type | None = None) -> ModuleType:
        if self._module is None:
            self._module = importlib.import_module(self._module_path)
        return self._module

    @property
    def module_path(self) -> str:
        """The module path this lazy descriptor will import."""
        return self._module_path

    @property
    def is_loaded(self) -> bool:
        """Whether the module has been imported yet."""
        return self._module is not None


def measure_import_time(module_name: str) -> float:
    """Measure how long a single module import takes.

    If the module is already in sys.modules, it is removed first to force
    a fresh import. The module is restored to sys.modules afterward.

    Args:
        module_name: Fully qualified module name (e.g. "reins.kernel.event.journal").

    Returns:
        Import time in milliseconds.
    """
    # Remove from cache to force fresh import
    cached = sys.modules.pop(module_name, None)
    # Also remove submodules that would short-circuit the import
    sub_keys = [k for k in sys.modules if k.startswith(module_name + ".")]
    cached_subs = {k: sys.modules.pop(k) for k in sub_keys}

    try:
        start = time.perf_counter()
        importlib.import_module(module_name)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
    finally:
        # Restore cached modules
        if cached is not None:
            sys.modules[module_name] = cached
        for k, v in cached_subs.items():
            sys.modules[k] = v

    return elapsed_ms


def get_import_breakdown() -> dict[str, float]:
    """Measure import time for each top-level reins submodule.

    Returns:
        Dict of module_name -> import time in ms, sorted slowest first.
    """
    submodules = [
        "reins.kernel",
        "reins.context",
        "reins.policy",
        "reins.execution",
        "reins.orchestration",
        "reins.cli",
        "reins.api",
        "reins.platform",
        "reins.workspace",
        "reins.isolation",
        "reins.task",
        "reins.performance",
    ]

    breakdown: dict[str, float] = {}
    for mod in submodules:
        try:
            elapsed = measure_import_time(mod)
            breakdown[mod] = elapsed
        except (ImportError, ModuleNotFoundError):
            # Skip modules that can't be imported
            pass

    # Sort slowest first
    return dict(sorted(breakdown.items(), key=lambda x: x[1], reverse=True))


def measure_startup() -> StartupMeasurement:
    """Measure CLI cold and warm startup times.

    Cold start: runs `python -c "import reins.cli.main"` in a subprocess.
    Warm start: times the import when modules are already loaded in-process.

    Returns:
        StartupMeasurement with cold/warm times and import breakdown.
    """
    # Cold start measurement via subprocess
    cold_ms = _measure_cold_start()

    # Warm start measurement (in-process, modules already cached)
    warm_ms = _measure_warm_start()

    # Import breakdown
    breakdown = get_import_breakdown()

    return StartupMeasurement(
        cold_ms=cold_ms,
        warm_ms=warm_ms,
        import_breakdown=breakdown,
        passed_cold=cold_ms < 300.0,
        passed_warm=warm_ms < 100.0,
    )


def _measure_cold_start() -> float:
    """Measure cold start time via subprocess."""
    cmd = [
        sys.executable,
        "-c",
        "import reins.cli.main",
    ]
    start = time.perf_counter()
    try:
        subprocess.run(cmd, capture_output=True, timeout=10.0, check=False)
    except subprocess.TimeoutExpired:
        return 10000.0  # 10s timeout = failed
    return (time.perf_counter() - start) * 1000.0


def _measure_warm_start() -> float:
    """Measure warm start time (modules already in sys.modules)."""
    # Ensure the module is loaded first (warm cache)
    importlib.import_module("reins.cli.main")

    start = time.perf_counter()
    importlib.import_module("reins.cli.main")
    return (time.perf_counter() - start) * 1000.0


def optimize_imports_report() -> str:
    """Run startup measurement and format a human-readable report.

    Highlights modules taking >50ms to import.

    Returns:
        Formatted report string.
    """
    measurement = measure_startup()

    lines: list[str] = [
        "=== Reins Startup Performance Report ===",
        "",
        f"Cold start: {measurement.cold_ms:.1f}ms "
        f"({'PASS' if measurement.passed_cold else 'FAIL'} < 300ms)",
        f"Warm start: {measurement.warm_ms:.1f}ms "
        f"({'PASS' if measurement.passed_warm else 'FAIL'} < 100ms)",
        "",
        "--- Import Breakdown (slowest first) ---",
    ]

    for module_name, elapsed in measurement.import_breakdown.items():
        marker = " [SLOW]" if elapsed > 50.0 else ""
        lines.append(f"  {module_name}: {elapsed:.1f}ms{marker}")

    slow_modules = [
        name for name, ms in measurement.import_breakdown.items() if ms > 50.0
    ]
    if slow_modules:
        lines.append("")
        lines.append(f"Modules exceeding 50ms: {len(slow_modules)}")
        lines.append("Consider using LazyModule for these imports.")

    return "\n".join(lines)
