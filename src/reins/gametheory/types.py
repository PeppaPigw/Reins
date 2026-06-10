from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

import ulid
from pydantic import BaseModel, ConfigDict, Field


def _new_ulid() -> str:
    return str(ulid.new())


def _utc_now() -> datetime:
    return datetime.now(UTC)


class GameKind(str, Enum):
    COOPERATIVE = "cooperative"
    COMPETITIVE = "competitive"
    MIXED_MOTIVE = "mixed_motive"
    AUCTION = "auction"
    BARGAINING = "bargaining"


class EquilibriumKind(str, Enum):
    NASH = "nash"
    PARETO_OPTIMAL = "pareto_optimal"
    DOMINANT_STRATEGY = "dominant_strategy"
    MINIMAX = "minimax"
    CORRELATED = "correlated"


class AuctionKind(str, Enum):
    FIRST_PRICE = "first_price"
    SECOND_PRICE = "second_price"
    ENGLISH = "english"
    DUTCH = "dutch"
    VICKREY = "vickrey"


class Strategy(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    name: str
    actions: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)


class Payoff(BaseModel):
    model_config = ConfigDict(frozen=True)

    agents: tuple[str, ...] = ()
    strategies: tuple[str, ...] = ()
    values: tuple[float, ...] = ()


class Game(BaseModel):
    model_config = ConfigDict(frozen=True)

    game_id: str = Field(default_factory=_new_ulid)
    name: str
    kind: GameKind = GameKind.MIXED_MOTIVE
    players: tuple[str, ...] = ()
    strategies: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    payoff_matrix: tuple[Payoff, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)


class Equilibrium(BaseModel):
    model_config = ConfigDict(frozen=True)

    equilibrium_id: str = Field(default_factory=_new_ulid)
    game_id: str
    kind: EquilibriumKind
    strategy_profile: dict[str, str] = Field(default_factory=dict)
    payoffs: dict[str, float] = Field(default_factory=dict)
    is_pareto_optimal: bool = False


class Bid(BaseModel):
    model_config = ConfigDict(frozen=True)

    bid_id: str = Field(default_factory=_new_ulid)
    agent_id: str
    resource: str
    amount: float
    priority: int = 0
    placed_at: datetime = Field(default_factory=_utc_now)


class AuctionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    result_id: str = Field(default_factory=_new_ulid)
    resource: str
    winner_id: str = ""
    winning_bid: float = 0.0
    price_paid: float = 0.0
    auction_kind: AuctionKind = AuctionKind.SECOND_PRICE
    all_bids: tuple[Bid, ...] = ()
    resolved_at: datetime = Field(default_factory=_utc_now)


class GameTheoryStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_games: int = 0
    total_equilibria: int = 0
    total_auctions: int = 0
    total_bids: int = 0
    avg_social_welfare: float = 0.0
    by_game_kind: dict[str, int] = Field(default_factory=dict)
