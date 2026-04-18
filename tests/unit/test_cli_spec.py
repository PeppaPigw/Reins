from __future__ import annotations

from pathlib import Path

from tests.unit.cli_helpers import create_repo, invoke


def test_spec_commands(monkeypatch, tmp_path: Path) -> None:
    repo = create_repo(tmp_path)

    init_result = invoke(repo, monkeypatch, ["spec", "init", "--package", "cli", "--layers", "commands,workflow"])
    assert init_result.exit_code == 0
    assert (repo / ".reins" / "spec" / "cli" / "index.md").exists()
    assert (repo / ".reins" / "spec" / "cli" / "commands" / "index.md").exists()

    add_layer = invoke(repo, monkeypatch, ["spec", "add-layer", "cli", "status"])
    assert add_layer.exit_code == 0
    assert (repo / ".reins" / "spec" / "cli" / "status" / "index.md").exists()
    package_index = (repo / ".reins" / "spec" / "cli" / "index.md").read_text(encoding="utf-8")
    assert "status/index.md" in package_index

    valid_spec = repo / ".reins" / "spec" / "backend.yaml"
    valid_spec.write_text(
        "spec_type: standing_law\ncontent: |\n  # Backend\n  Use typed errors.\n",
        encoding="utf-8",
    )
    validate = invoke(repo, monkeypatch, ["spec", "validate", str(valid_spec)])
    assert validate.exit_code == 0

    invalid_spec = repo / ".reins" / "spec" / "invalid.yaml"
    invalid_spec.write_text("spec_type: nope\n", encoding="utf-8")
    invalid = invoke(repo, monkeypatch, ["spec", "validate", str(invalid_spec)])
    assert invalid.exit_code == 1

    list_result = invoke(repo, monkeypatch, ["spec", "list", "--package", "cli"])
    assert list_result.exit_code == 0
    assert "commands/index.md" in list_result.output
