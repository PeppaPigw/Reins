from __future__ import annotations

from pathlib import Path

from reins.context.compiler import ContextCompiler
from reins.platform.project_detector import ProjectDetector


def test_context_compiler_prioritizes_package_layer_sources(tmp_path: Path) -> None:
    spec_root = tmp_path / ".reins" / "spec"
    (spec_root / "auth" / "backend").mkdir(parents=True, exist_ok=True)
    (spec_root / "backend").mkdir(parents=True, exist_ok=True)
    (spec_root / "guides").mkdir(parents=True, exist_ok=True)

    compiler = ContextCompiler()
    sources = compiler.resolve_spec_sources(spec_root, task_type="backend", package="auth")

    identifiers = [source.identifier for source in sources]
    assert identifiers == ["package:auth:backend", "backend", "guides"]


def test_context_compiler_keeps_package_overview_for_custom_layers(tmp_path: Path) -> None:
    spec_root = tmp_path / ".reins" / "spec"
    (spec_root / "auth" / "commands").mkdir(parents=True, exist_ok=True)
    (spec_root / "auth" / "index.md").write_text("# Auth\n", encoding="utf-8")
    (spec_root / "backend").mkdir(parents=True, exist_ok=True)
    (spec_root / "guides").mkdir(parents=True, exist_ok=True)

    compiler = ContextCompiler()
    sources = compiler.resolve_spec_sources(spec_root, task_type="backend", package="auth")

    identifiers = [source.identifier for source in sources]
    assert identifiers[:2] == ["package:auth", "package:auth:commands"]
    assert identifiers[-2:] == ["backend", "guides"]


def test_project_detector_detects_and_inferrs_monorepo_packages(tmp_path: Path) -> None:
    (tmp_path / "packages" / "auth" / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "packages" / "billing" / "src").mkdir(parents=True, exist_ok=True)
    billing_file = tmp_path / "packages" / "billing" / "src" / "api.py"
    billing_file.write_text("print('billing')\n", encoding="utf-8")

    detector = ProjectDetector()
    detected = detector.detect_packages(tmp_path)

    assert detected == ["auth", "billing"]
    assert detector.infer_package(tmp_path, [billing_file]) == "billing"
