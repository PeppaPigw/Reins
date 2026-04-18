from __future__ import annotations

from pathlib import Path

from reins.cli.commands.spec import ensure_standard_spec_layout
from reins.context.types import SpecLayer


def test_spec_layer_defaults_cover_project_types() -> None:
    assert SpecLayer.default_layers_for_project_type("backend") == (
        SpecLayer.BACKEND,
        SpecLayer.UNIT_TEST,
        SpecLayer.INTEGRATION_TEST,
        SpecLayer.GUIDES,
    )
    assert SpecLayer.default_layers_for_project_type("frontend") == (
        SpecLayer.FRONTEND,
        SpecLayer.UNIT_TEST,
        SpecLayer.INTEGRATION_TEST,
        SpecLayer.GUIDES,
    )
    assert SpecLayer.default_layers_for_project_type("fullstack") == (
        SpecLayer.BACKEND,
        SpecLayer.FRONTEND,
        SpecLayer.UNIT_TEST,
        SpecLayer.INTEGRATION_TEST,
        SpecLayer.GUIDES,
    )


def test_ensure_standard_spec_layout_creates_global_and_package_layers(tmp_path: Path) -> None:
    created = ensure_standard_spec_layout(tmp_path, project_type="backend", package="auth")

    assert created
    for layer in ("backend", "frontend", "unit-test", "integration-test", "guides"):
        assert (tmp_path / ".reins" / "spec" / layer / "index.md").exists()

    for layer in ("backend", "unit-test", "integration-test"):
        assert (tmp_path / ".reins" / "spec" / "auth" / layer / "index.md").exists()
    assert not (tmp_path / ".reins" / "spec" / "auth" / "guides").exists()
