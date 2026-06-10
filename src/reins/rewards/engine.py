from __future__ import annotations

import math
from collections import defaultdict

from reins.rewards.types import (
    RewardDimension,
    RewardPolicy,
    RewardProfile,
    RewardSignal,
    RewardStats,
    ShapingStrategy,
)


class RewardShaper:
    """Adaptive reward signals for reinforcement-based agent learning.

    Shapes raw reward values using configurable strategies per dimension,
    tracks agent reward profiles, and adapts weights over time.
    """

    def __init__(self) -> None:
        self._policies: dict[RewardDimension, RewardPolicy] = {}
        self._signals: dict[str, list[RewardSignal]] = defaultdict(list)
        self._register_defaults()

    def register_policy(self, policy: RewardPolicy) -> None:
        self._policies[policy.dimension] = policy

    def shape(self, agent_id: str, dimension: RewardDimension,
              raw_value: float, metadata: dict | None = None) -> RewardSignal:
        policy = self._policies.get(dimension, RewardPolicy(dimension=dimension))
        shaped = self._apply_shaping(raw_value, policy)

        signal = RewardSignal(
            agent_id=agent_id,
            dimension=dimension,
            raw_value=raw_value,
            shaped_value=shaped,
            weight=policy.weight,
            metadata=metadata or {},
        )
        self._signals[agent_id].append(signal)
        return signal

    def get_profile(self, agent_id: str) -> RewardProfile:
        signals = self._signals.get(agent_id, [])
        if not signals:
            return RewardProfile(agent_id=agent_id)

        total = sum(s.shaped_value * s.weight for s in signals)
        avg = total / len(signals)

        by_dim: dict[str, float] = defaultdict(float)
        for s in signals:
            by_dim[s.dimension.value] += s.shaped_value * s.weight

        trend = self._compute_trend(signals)

        return RewardProfile(
            agent_id=agent_id,
            total_reward=total,
            avg_reward=avg,
            signal_count=len(signals),
            by_dimension=dict(by_dim),
            trend=trend,
        )

    def get_signals(self, agent_id: str, dimension: RewardDimension | None = None,
                    last_n: int | None = None) -> list[RewardSignal]:
        signals = self._signals.get(agent_id, [])
        if dimension:
            signals = [s for s in signals if s.dimension == dimension]
        if last_n:
            signals = signals[-last_n:]
        return signals

    def get_stats(self) -> RewardStats:
        total_signals = sum(len(s) for s in self._signals.values())
        all_signals = [s for sigs in self._signals.values() for s in sigs]
        avg_shaped = (
            sum(s.shaped_value for s in all_signals) / len(all_signals)
            if all_signals else 0.0
        )

        by_dim: dict[str, int] = defaultdict(int)
        by_strat: dict[str, int] = defaultdict(int)
        for s in all_signals:
            by_dim[s.dimension.value] += 1
            policy = self._policies.get(s.dimension)
            if policy:
                by_strat[policy.strategy.value] += 1

        return RewardStats(
            agents_tracked=len(self._signals),
            total_signals=total_signals,
            avg_shaped_reward=avg_shaped,
            by_dimension=dict(by_dim),
            by_strategy=dict(by_strat),
        )

    def _apply_shaping(self, raw: float, policy: RewardPolicy) -> float:
        if policy.strategy == ShapingStrategy.LINEAR:
            shaped = raw * policy.weight
        elif policy.strategy == ShapingStrategy.EXPONENTIAL:
            shaped = math.copysign(abs(raw) ** 1.5, raw) * policy.weight
        elif policy.strategy == ShapingStrategy.THRESHOLD:
            if raw >= policy.threshold:
                shaped = 1.0 * policy.weight
            else:
                shaped = -0.5 * policy.weight
        elif policy.strategy == ShapingStrategy.DIMINISHING:
            shaped = math.copysign(math.log1p(abs(raw)), raw) * policy.weight
        elif policy.strategy == ShapingStrategy.PENALTY_DOMINANT:
            if raw >= 0:
                shaped = raw * 0.5 * policy.weight
            else:
                shaped = raw * 2.0 * policy.weight
        else:
            shaped = raw * policy.weight

        return max(policy.floor, min(policy.ceiling, shaped))

    def _compute_trend(self, signals: list[RewardSignal]) -> float:
        if len(signals) < 4:
            return 0.0
        mid = len(signals) // 2
        first_half = signals[:mid]
        second_half = signals[mid:]
        avg_first = sum(s.shaped_value for s in first_half) / len(first_half)
        avg_second = sum(s.shaped_value for s in second_half) / len(second_half)
        return avg_second - avg_first

    def _register_defaults(self) -> None:
        self._policies[RewardDimension.CORRECTNESS] = RewardPolicy(
            dimension=RewardDimension.CORRECTNESS, weight=2.0,
            strategy=ShapingStrategy.THRESHOLD, threshold=0.8,
        )
        self._policies[RewardDimension.EFFICIENCY] = RewardPolicy(
            dimension=RewardDimension.EFFICIENCY, weight=1.0,
            strategy=ShapingStrategy.DIMINISHING,
        )
        self._policies[RewardDimension.SAFETY] = RewardPolicy(
            dimension=RewardDimension.SAFETY, weight=3.0,
            strategy=ShapingStrategy.PENALTY_DOMINANT,
        )
        self._policies[RewardDimension.CREATIVITY] = RewardPolicy(
            dimension=RewardDimension.CREATIVITY, weight=0.8,
            strategy=ShapingStrategy.LINEAR,
        )
        self._policies[RewardDimension.COMPLIANCE] = RewardPolicy(
            dimension=RewardDimension.COMPLIANCE, weight=2.5,
            strategy=ShapingStrategy.THRESHOLD, threshold=0.9,
        )
        self._policies[RewardDimension.USER_SATISFACTION] = RewardPolicy(
            dimension=RewardDimension.USER_SATISFACTION, weight=1.5,
            strategy=ShapingStrategy.LINEAR,
        )
        self._policies[RewardDimension.COST] = RewardPolicy(
            dimension=RewardDimension.COST, weight=1.0,
            strategy=ShapingStrategy.PENALTY_DOMINANT,
        )
        self._policies[RewardDimension.SPEED] = RewardPolicy(
            dimension=RewardDimension.SPEED, weight=1.0,
            strategy=ShapingStrategy.DIMINISHING,
        )
