from __future__ import annotations

from pathlib import Path

from reins.config.loader import ConfigLoader
from reins.config.types import PackageConfig, ReinsConfig


def test_config_loader_returns_defaults_when_missing(tmp_path: Path) -> None:
    loader = ConfigLoader(tmp_path / ".reins")

    config = loader.load()

    assert config == ReinsConfig()


def test_config_loader_parses_nested_yaml(tmp_path: Path) -> None:
    reins_root = tmp_path / ".reins"
    reins_root.mkdir()
    (reins_root / "config.yaml").write_text(
        """
session_commit_message: "chore: snapshot workspace"
max_journal_lines: 1234
packages:
  cli:
    path: packages/cli
  docs:
    path: docs-site
    type: submodule
default_package: cli
hooks:
  after_create:
    - python3 .reins/hooks/examples/linear_sync.py create
  after_start:
    - python3 .reins/hooks/examples/linear_sync.py start
update:
  skip:
    - .agents/skills/
""".strip(),
        encoding="utf-8",
    )

    config = ConfigLoader(reins_root).load()

    assert config.session_commit_message == "chore: snapshot workspace"
    assert config.max_journal_lines == 1234
    assert config.packages == {
        "cli": PackageConfig(path="packages/cli", type="package"),
        "docs": PackageConfig(path="docs-site", type="submodule"),
    }
    assert config.default_package == "cli"
    assert config.hooks.after_create == [
        "python3 .reins/hooks/examples/linear_sync.py create"
    ]
    assert config.hooks.after_start == [
        "python3 .reins/hooks/examples/linear_sync.py start"
    ]
    assert config.update.skip == [".agents/skills/"]


def test_config_loader_save_round_trips(tmp_path: Path) -> None:
    reins_root = tmp_path / ".reins"
    loader = ConfigLoader(reins_root)
    config = ReinsConfig(
        session_commit_message="chore: save journal",
        max_journal_lines=2500,
        packages={"cli": PackageConfig(path="packages/cli")},
        default_package="cli",
    )

    loader.save(config)

    reloaded = loader.load()

    assert reloaded == config
