from __future__ import annotations

from pathlib import Path

import pytest

from reins.intelligence.strategy.trust import TrustModel
from reins.intelligence.types import TrustLevel


@pytest.fixture
def trust_model(tmp_path: Path) -> TrustModel:
    return TrustModel(tmp_path / "trust")


def test_new_domain_starts_supervised(trust_model: TrustModel) -> None:
    score = trust_model.get_domain_trust("testing")
    assert score.level == TrustLevel.supervised
    assert score.score == 0.0


async def test_trust_promotes_after_successes(trust_model: TrustModel) -> None:
    for _ in range(6):
        await trust_model.record_outcome("testing", success=True)

    score = trust_model.get_domain_trust("testing")
    assert score.level == TrustLevel.semi_auto
    assert score.effective_successes >= 5.0


async def test_trust_is_domain_isolated(trust_model: TrustModel) -> None:
    for _ in range(6):
        await trust_model.record_outcome("testing", success=True)

    testing = trust_model.get_domain_trust("testing")
    deployment = trust_model.get_domain_trust("deployment")

    assert testing.level == TrustLevel.semi_auto
    assert deployment.level == TrustLevel.supervised


async def test_failures_reduce_trust_score(trust_model: TrustModel) -> None:
    for _ in range(6):
        await trust_model.record_outcome("testing", success=True)
    for _ in range(3):
        await trust_model.record_outcome("testing", success=False, severity=2.0)

    score = trust_model.get_domain_trust("testing")
    assert score.score < 0.8


async def test_hard_demotion_overrides_computed_level(trust_model: TrustModel) -> None:
    for _ in range(6):
        await trust_model.record_outcome("testing", success=True)

    score = trust_model.get_domain_trust("testing")
    assert score.level == TrustLevel.semi_auto

    await trust_model.hard_demote("testing", TrustLevel.supervised, "policy bypass")

    score = trust_model.get_domain_trust("testing")
    assert score.level == TrustLevel.supervised


async def test_persistence_across_reload(tmp_path: Path) -> None:
    store = tmp_path / "trust"

    model1 = TrustModel(store)
    for _ in range(6):
        await model1.record_outcome("testing", success=True)

    model2 = TrustModel(store)
    score = model2.get_domain_trust("testing")
    assert score.level == TrustLevel.semi_auto
