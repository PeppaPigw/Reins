"""Tests for reward shaping with adaptive reinforcement signals."""

from __future__ import annotations

import pytest

from reins.rewards import (
    RewardDimension,
    RewardPolicy,
    RewardProfile,
    RewardShaper,
    RewardSignal,
    RewardStats,
    ShapingStrategy,
)


@pytest.fixture
def shaper() -> RewardShaper:
    return RewardShaper()


def test_shape_returns_signal(shaper):
    signal = shaper.shape("agent-1", RewardDimension.CORRECTNESS, 0.9)
    assert isinstance(signal, RewardSignal)
    assert signal.agent_id == "agent-1"
    assert signal.raw_value == 0.9


def test_shape_linear(shaper):
    shaper.register_policy(RewardPolicy(
        dimension=RewardDimension.CREATIVITY, weight=1.0,
        strategy=ShapingStrategy.LINEAR,
    ))
    signal = shaper.shape("a", RewardDimension.CREATIVITY, 0.5)
    assert signal.shaped_value == pytest.approx(0.5)


def test_shape_threshold_above(shaper):
    shaper.register_policy(RewardPolicy(
        dimension=RewardDimension.CORRECTNESS, weight=1.0,
        strategy=ShapingStrategy.THRESHOLD, threshold=0.7,
    ))
    signal = shaper.shape("a", RewardDimension.CORRECTNESS, 0.8)
    assert signal.shaped_value == pytest.approx(1.0)


def test_shape_threshold_below(shaper):
    shaper.register_policy(RewardPolicy(
        dimension=RewardDimension.CORRECTNESS, weight=1.0,
        strategy=ShapingStrategy.THRESHOLD, threshold=0.7,
    ))
    signal = shaper.shape("a", RewardDimension.CORRECTNESS, 0.5)
    assert signal.shaped_value == pytest.approx(-0.5)


def test_shape_diminishing(shaper):
    shaper.register_policy(RewardPolicy(
        dimension=RewardDimension.EFFICIENCY, weight=1.0,
        strategy=ShapingStrategy.DIMINISHING,
    ))
    s1 = shaper.shape("a", RewardDimension.EFFICIENCY, 1.0)
    s2 = shaper.shape("a", RewardDimension.EFFICIENCY, 10.0)
    assert s2.shaped_value > s1.shaped_value
    assert s2.shaped_value < 10.0 * s1.shaped_value


def test_shape_penalty_dominant_positive(shaper):
    shaper.register_policy(RewardPolicy(
        dimension=RewardDimension.SAFETY, weight=1.0,
        strategy=ShapingStrategy.PENALTY_DOMINANT,
    ))
    signal = shaper.shape("a", RewardDimension.SAFETY, 0.8)
    assert signal.shaped_value == pytest.approx(0.4)


def test_shape_penalty_dominant_negative(shaper):
    shaper.register_policy(RewardPolicy(
        dimension=RewardDimension.SAFETY, weight=1.0,
        strategy=ShapingStrategy.PENALTY_DOMINANT,
    ))
    signal = shaper.shape("a", RewardDimension.SAFETY, -0.5)
    assert signal.shaped_value == pytest.approx(-1.0)


def test_shape_exponential(shaper):
    shaper.register_policy(RewardPolicy(
        dimension=RewardDimension.CREATIVITY, weight=1.0,
        strategy=ShapingStrategy.EXPONENTIAL,
    ))
    signal = shaper.shape("a", RewardDimension.CREATIVITY, 0.5)
    assert signal.shaped_value < 0.5


def test_shape_respects_floor_ceiling(shaper):
    shaper.register_policy(RewardPolicy(
        dimension=RewardDimension.COST, weight=10.0,
        strategy=ShapingStrategy.LINEAR, floor=-1.0, ceiling=1.0,
    ))
    signal = shaper.shape("a", RewardDimension.COST, 5.0)
    assert signal.shaped_value <= 1.0


def test_shape_floor_clamp(shaper):
    shaper.register_policy(RewardPolicy(
        dimension=RewardDimension.COST, weight=10.0,
        strategy=ShapingStrategy.LINEAR, floor=-1.0, ceiling=1.0,
    ))
    signal = shaper.shape("a", RewardDimension.COST, -5.0)
    assert signal.shaped_value >= -1.0


def test_get_profile_empty(shaper):
    profile = shaper.get_profile("agent-1")
    assert profile.signal_count == 0
    assert profile.total_reward == 0.0


def test_get_profile_with_signals(shaper):
    shaper.shape("agent-1", RewardDimension.CREATIVITY, 0.5)
    shaper.shape("agent-1", RewardDimension.CREATIVITY, 0.7)
    profile = shaper.get_profile("agent-1")
    assert profile.signal_count == 2
    assert profile.total_reward != 0.0
    assert RewardDimension.CREATIVITY.value in profile.by_dimension


def test_get_profile_trend_positive(shaper):
    shaper.register_policy(RewardPolicy(
        dimension=RewardDimension.CREATIVITY, weight=1.0,
        strategy=ShapingStrategy.LINEAR,
    ))
    for v in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
        shaper.shape("a", RewardDimension.CREATIVITY, v)
    profile = shaper.get_profile("a")
    assert profile.trend > 0


def test_get_profile_trend_negative(shaper):
    shaper.register_policy(RewardPolicy(
        dimension=RewardDimension.CREATIVITY, weight=1.0,
        strategy=ShapingStrategy.LINEAR,
    ))
    for v in [0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1]:
        shaper.shape("a", RewardDimension.CREATIVITY, v)
    profile = shaper.get_profile("a")
    assert profile.trend < 0


def test_get_signals_all(shaper):
    shaper.shape("a", RewardDimension.CORRECTNESS, 0.9)
    shaper.shape("a", RewardDimension.SAFETY, 0.8)
    signals = shaper.get_signals("a")
    assert len(signals) == 2


def test_get_signals_by_dimension(shaper):
    shaper.shape("a", RewardDimension.CORRECTNESS, 0.9)
    shaper.shape("a", RewardDimension.SAFETY, 0.8)
    signals = shaper.get_signals("a", dimension=RewardDimension.CORRECTNESS)
    assert len(signals) == 1


def test_get_signals_last_n(shaper):
    for i in range(10):
        shaper.shape("a", RewardDimension.CREATIVITY, float(i) / 10)
    signals = shaper.get_signals("a", last_n=3)
    assert len(signals) == 3


def test_get_signals_empty(shaper):
    assert shaper.get_signals("unknown") == []


def test_register_custom_policy(shaper):
    policy = RewardPolicy(
        dimension=RewardDimension.SPEED, weight=5.0,
        strategy=ShapingStrategy.LINEAR,
    )
    shaper.register_policy(policy)
    signal = shaper.shape("a", RewardDimension.SPEED, 0.5)
    assert signal.shaped_value == pytest.approx(1.0, abs=0.01)


def test_stats_empty():
    s = RewardShaper()
    stats = s.get_stats()
    assert stats.agents_tracked == 0
    assert stats.total_signals == 0


def test_stats_with_data(shaper):
    shaper.shape("a", RewardDimension.CORRECTNESS, 0.9)
    shaper.shape("b", RewardDimension.SAFETY, 0.5)
    stats = shaper.get_stats()
    assert stats.agents_tracked == 2
    assert stats.total_signals == 2
    assert RewardDimension.CORRECTNESS.value in stats.by_dimension


def test_multiple_agents_independent(shaper):
    shaper.shape("a", RewardDimension.CREATIVITY, 0.9)
    shaper.shape("b", RewardDimension.CREATIVITY, 0.1)
    profile_a = shaper.get_profile("a")
    profile_b = shaper.get_profile("b")
    assert profile_a.signal_count == 1
    assert profile_b.signal_count == 1


def test_weight_affects_shaped_value(shaper):
    shaper.register_policy(RewardPolicy(
        dimension=RewardDimension.SPEED, weight=2.0,
        strategy=ShapingStrategy.LINEAR, ceiling=5.0,
    ))
    signal = shaper.shape("a", RewardDimension.SPEED, 0.5)
    assert signal.shaped_value == pytest.approx(1.0)


def test_metadata_preserved(shaper):
    signal = shaper.shape("a", RewardDimension.CORRECTNESS, 0.9,
                          metadata={"task": "code-review"})
    assert signal.metadata == {"task": "code-review"}
