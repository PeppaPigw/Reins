from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from reins.cli.main import app


def test_init_creates_layer_hierarchy_for_package(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\nversion = '0.1.0'\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(repo_root)

    result = CliRunner().invoke(
        app,
        [
            "init",
            "--platform",
            "codex",
            "--project-type",
            "backend",
            "--developer",
            "peppa",
            "--package",
            "auth",
        ],
    )

    assert result.exit_code == 0
    for layer in ("backend", "frontend", "unit-test", "integration-test", "guides"):
        assert (repo_root / ".reins" / "spec" / layer / "index.md").exists()
    for layer in ("backend", "unit-test", "integration-test"):
        assert (repo_root / ".reins" / "spec" / "auth" / layer / "index.md").exists()
