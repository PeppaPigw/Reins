from __future__ import annotations

import pytest

from tests.integration.helpers import (
    EventJournal,
    build_orchestrator_bundle,
    make_harness,
)


@pytest.fixture
def integration_harness(tmp_path, monkeypatch):
    return make_harness(tmp_path, monkeypatch, git=True)


@pytest.fixture
def repo_root(integration_harness):
    return integration_harness.repo_root


@pytest.fixture
def journal(tmp_path):
    return EventJournal(tmp_path / "journal.jsonl")


@pytest.fixture
def orchestrator_bundle(tmp_path, repo_root):
    return build_orchestrator_bundle(tmp_path, repo_root=repo_root)
