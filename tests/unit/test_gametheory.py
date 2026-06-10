"""Tests for game theory engine with Nash equilibria and auctions."""

from __future__ import annotations

import pytest

from reins.gametheory import (
    AuctionKind,
    AuctionResult,
    Bid,
    Equilibrium,
    EquilibriumKind,
    Game,
    GameKind,
    GameTheoryEngine,
    GameTheoryStats,
    Payoff,
)


@pytest.fixture
def engine() -> GameTheoryEngine:
    return GameTheoryEngine()


@pytest.fixture
def prisoners_dilemma(engine) -> Game:
    """Classic Prisoner's Dilemma."""
    return engine.create_game(
        name="Prisoner's Dilemma",
        kind=GameKind.MIXED_MOTIVE,
        players=["alice", "bob"],
        strategies={"alice": ["cooperate", "defect"], "bob": ["cooperate", "defect"]},
        payoffs=[
            Payoff(agents=("alice", "bob"), strategies=("cooperate", "cooperate"), values=(3.0, 3.0)),
            Payoff(agents=("alice", "bob"), strategies=("cooperate", "defect"), values=(0.0, 5.0)),
            Payoff(agents=("alice", "bob"), strategies=("defect", "cooperate"), values=(5.0, 0.0)),
            Payoff(agents=("alice", "bob"), strategies=("defect", "defect"), values=(1.0, 1.0)),
        ],
    )


def test_create_game(engine, prisoners_dilemma):
    assert engine.get_game(prisoners_dilemma.game_id) is not None


def test_get_game_not_found(engine):
    assert engine.get_game("nonexistent") is None


def test_find_nash_prisoners_dilemma(engine, prisoners_dilemma):
    equilibria = engine.find_nash_equilibria(prisoners_dilemma.game_id)
    assert len(equilibria) == 1
    eq = equilibria[0]
    assert eq.strategy_profile["alice"] == "defect"
    assert eq.strategy_profile["bob"] == "defect"


def test_nash_equilibrium_payoffs(engine, prisoners_dilemma):
    equilibria = engine.find_nash_equilibria(prisoners_dilemma.game_id)
    eq = equilibria[0]
    assert eq.payoffs["alice"] == 1.0
    assert eq.payoffs["bob"] == 1.0


def test_nash_not_pareto_optimal(engine, prisoners_dilemma):
    equilibria = engine.find_nash_equilibria(prisoners_dilemma.game_id)
    assert not equilibria[0].is_pareto_optimal


def test_dominant_strategy(engine, prisoners_dilemma):
    dominant = engine.find_dominant_strategies(prisoners_dilemma.game_id)
    assert dominant["alice"] == "defect"
    assert dominant["bob"] == "defect"


def test_no_dominant_strategy(engine):
    game = engine.create_game(
        name="Matching Pennies",
        kind=GameKind.COMPETITIVE,
        players=["p1", "p2"],
        strategies={"p1": ["heads", "tails"], "p2": ["heads", "tails"]},
        payoffs=[
            Payoff(strategies=("heads", "heads"), values=(1.0, -1.0)),
            Payoff(strategies=("heads", "tails"), values=(-1.0, 1.0)),
            Payoff(strategies=("tails", "heads"), values=(-1.0, 1.0)),
            Payoff(strategies=("tails", "tails"), values=(1.0, -1.0)),
        ],
    )
    dominant = engine.find_dominant_strategies(game.game_id)
    assert dominant["p1"] is None
    assert dominant["p2"] is None


def test_social_welfare(engine, prisoners_dilemma):
    welfare = engine.compute_social_welfare(
        prisoners_dilemma.game_id, {"alice": "cooperate", "bob": "cooperate"}
    )
    assert welfare == 6.0


def test_social_welfare_defect(engine, prisoners_dilemma):
    welfare = engine.compute_social_welfare(
        prisoners_dilemma.game_id, {"alice": "defect", "bob": "defect"}
    )
    assert welfare == 2.0


def test_minimax(engine, prisoners_dilemma):
    strategy, value = engine.compute_minimax(prisoners_dilemma.game_id, "alice")
    assert strategy == "defect"
    assert value == 1.0


def test_minimax_nonexistent_game(engine):
    strategy, value = engine.compute_minimax("nonexistent", "alice")
    assert strategy is None


def test_place_bid(engine):
    bid = engine.place_bid("agent-1", "gpu_slot", 10.0)
    assert bid.agent_id == "agent-1"
    assert bid.amount == 10.0


def test_resolve_auction_second_price(engine):
    engine.place_bid("a", "gpu", 10.0)
    engine.place_bid("b", "gpu", 15.0)
    engine.place_bid("c", "gpu", 8.0)
    result = engine.resolve_auction("gpu", AuctionKind.SECOND_PRICE)
    assert result.winner_id == "b"
    assert result.winning_bid == 15.0
    assert result.price_paid == 10.0


def test_resolve_auction_first_price(engine):
    engine.place_bid("a", "mem", 20.0)
    engine.place_bid("b", "mem", 12.0)
    result = engine.resolve_auction("mem", AuctionKind.FIRST_PRICE)
    assert result.winner_id == "a"
    assert result.price_paid == 20.0


def test_resolve_auction_no_bids(engine):
    result = engine.resolve_auction("empty_resource")
    assert result.winner_id == ""


def test_resolve_auction_single_bid(engine):
    engine.place_bid("solo", "rare", 5.0)
    result = engine.resolve_auction("rare", AuctionKind.SECOND_PRICE)
    assert result.winner_id == "solo"
    assert result.price_paid == 5.0


def test_auction_clears_bids(engine):
    engine.place_bid("a", "slot", 10.0)
    engine.resolve_auction("slot")
    engine.place_bid("b", "slot", 5.0)
    result = engine.resolve_auction("slot")
    assert result.winner_id == "b"


def test_get_auction_results(engine):
    engine.place_bid("a", "r1", 10.0)
    engine.resolve_auction("r1")
    engine.place_bid("b", "r2", 5.0)
    engine.resolve_auction("r2")
    assert len(engine.get_auction_results()) == 2


def test_get_auction_results_by_resource(engine):
    engine.place_bid("a", "r1", 10.0)
    engine.resolve_auction("r1")
    engine.place_bid("b", "r2", 5.0)
    engine.resolve_auction("r2")
    assert len(engine.get_auction_results(resource="r1")) == 1


def test_multiple_nash_equilibria(engine):
    game = engine.create_game(
        name="Battle of Sexes",
        kind=GameKind.COOPERATIVE,
        players=["p1", "p2"],
        strategies={"p1": ["opera", "football"], "p2": ["opera", "football"]},
        payoffs=[
            Payoff(strategies=("opera", "opera"), values=(3.0, 2.0)),
            Payoff(strategies=("opera", "football"), values=(0.0, 0.0)),
            Payoff(strategies=("football", "opera"), values=(0.0, 0.0)),
            Payoff(strategies=("football", "football"), values=(2.0, 3.0)),
        ],
    )
    equilibria = engine.find_nash_equilibria(game.game_id)
    assert len(equilibria) == 2


def test_stats_empty():
    eng = GameTheoryEngine()
    stats = eng.get_stats()
    assert stats.total_games == 0
    assert stats.total_equilibria == 0


def test_stats_with_data(engine, prisoners_dilemma):
    engine.find_nash_equilibria(prisoners_dilemma.game_id)
    engine.place_bid("a", "r", 10.0)
    engine.resolve_auction("r")
    stats = engine.get_stats()
    assert stats.total_games == 1
    assert stats.total_equilibria == 1
    assert stats.total_auctions == 1
    assert stats.avg_social_welfare > 0
