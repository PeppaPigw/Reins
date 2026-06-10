from __future__ import annotations

from collections import defaultdict
from itertools import product

from reins.gametheory.types import (
    AuctionKind,
    AuctionResult,
    Bid,
    Equilibrium,
    EquilibriumKind,
    Game,
    GameKind,
    GameTheoryStats,
    Payoff,
    Strategy,
)


class GameTheoryEngine:
    """Game-theoretic coordination with Nash equilibria and auction mechanisms.

    Provides mechanism design for multi-agent resource allocation,
    equilibrium computation for strategic interactions, and
    incentive-compatible auction protocols.
    """

    def __init__(self) -> None:
        self._games: dict[str, Game] = {}
        self._equilibria: list[Equilibrium] = []
        self._bids: dict[str, list[Bid]] = defaultdict(list)
        self._auction_results: list[AuctionResult] = []

    def create_game(self, name: str, kind: GameKind,
                    players: list[str],
                    strategies: dict[str, list[str]],
                    payoffs: list[Payoff]) -> Game:
        game = Game(
            name=name,
            kind=kind,
            players=tuple(players),
            strategies={k: tuple(v) for k, v in strategies.items()},
            payoff_matrix=tuple(payoffs),
        )
        self._games[game.game_id] = game
        return game

    def get_game(self, game_id: str) -> Game | None:
        return self._games.get(game_id)

    def find_nash_equilibria(self, game_id: str) -> list[Equilibrium]:
        game = self._games.get(game_id)
        if not game or not game.players:
            return []

        equilibria = []
        strategy_lists = [list(game.strategies.get(p, ())) for p in game.players]
        if not all(strategy_lists):
            return []

        for profile in product(*strategy_lists):
            strategy_map = dict(zip(game.players, profile))
            if self._is_nash(game, strategy_map):
                payoffs = self._get_payoffs(game, strategy_map)
                eq = Equilibrium(
                    game_id=game_id,
                    kind=EquilibriumKind.NASH,
                    strategy_profile=strategy_map,
                    payoffs=payoffs,
                    is_pareto_optimal=self._is_pareto_optimal(game, payoffs),
                )
                self._equilibria.append(eq)
                equilibria.append(eq)

        return equilibria

    def find_dominant_strategies(self, game_id: str) -> dict[str, str | None]:
        game = self._games.get(game_id)
        if not game:
            return {}

        result: dict[str, str | None] = {}
        for player in game.players:
            dominant = self._find_dominant_for_player(game, player)
            result[player] = dominant
        return result

    def compute_social_welfare(self, game_id: str,
                               strategy_profile: dict[str, str]) -> float:
        game = self._games.get(game_id)
        if not game:
            return 0.0
        payoffs = self._get_payoffs(game, strategy_profile)
        return sum(payoffs.values())

    def place_bid(self, agent_id: str, resource: str, amount: float,
                  priority: int = 0) -> Bid:
        bid = Bid(agent_id=agent_id, resource=resource, amount=amount, priority=priority)
        self._bids[resource].append(bid)
        return bid

    def resolve_auction(self, resource: str,
                        kind: AuctionKind = AuctionKind.SECOND_PRICE) -> AuctionResult:
        bids = self._bids.get(resource, [])
        if not bids:
            result = AuctionResult(resource=resource, auction_kind=kind)
            self._auction_results.append(result)
            return result

        sorted_bids = sorted(bids, key=lambda b: (-b.amount, -b.priority))
        winner = sorted_bids[0]

        if kind == AuctionKind.FIRST_PRICE:
            price = winner.amount
        elif kind in (AuctionKind.SECOND_PRICE, AuctionKind.VICKREY):
            price = sorted_bids[1].amount if len(sorted_bids) > 1 else winner.amount
        else:
            price = winner.amount

        result = AuctionResult(
            resource=resource,
            winner_id=winner.agent_id,
            winning_bid=winner.amount,
            price_paid=price,
            auction_kind=kind,
            all_bids=tuple(sorted_bids),
        )
        self._auction_results.append(result)
        self._bids[resource] = []
        return result

    def get_auction_results(self, resource: str | None = None) -> list[AuctionResult]:
        results = self._auction_results
        if resource:
            results = [r for r in results if r.resource == resource]
        return results

    def compute_minimax(self, game_id: str, player: str) -> tuple[str | None, float]:
        game = self._games.get(game_id)
        if not game or player not in game.players:
            return None, 0.0

        player_strategies = list(game.strategies.get(player, ()))
        if not player_strategies:
            return None, 0.0

        other_players = [p for p in game.players if p != player]
        other_strategy_lists = [list(game.strategies.get(p, ())) for p in other_players]

        best_strategy = None
        best_worst_case = float("-inf")

        for strategy in player_strategies:
            worst_case = float("inf")
            for other_profile in product(*other_strategy_lists):
                profile = {}
                profile[player] = strategy
                for p, s in zip(other_players, other_profile):
                    profile[p] = s
                payoffs = self._get_payoffs(game, profile)
                player_payoff = payoffs.get(player, 0.0)
                worst_case = min(worst_case, player_payoff)

            if worst_case > best_worst_case:
                best_worst_case = worst_case
                best_strategy = strategy

        return best_strategy, best_worst_case

    def get_stats(self) -> GameTheoryStats:
        by_kind: dict[str, int] = defaultdict(int)
        for g in self._games.values():
            by_kind[g.kind.value] += 1

        total_bids = sum(len(b) for b in self._bids.values())
        total_bids += sum(len(r.all_bids) for r in self._auction_results)

        welfare_values = []
        for eq in self._equilibria:
            welfare_values.append(sum(eq.payoffs.values()))
        avg_welfare = sum(welfare_values) / len(welfare_values) if welfare_values else 0.0

        return GameTheoryStats(
            total_games=len(self._games),
            total_equilibria=len(self._equilibria),
            total_auctions=len(self._auction_results),
            total_bids=total_bids,
            avg_social_welfare=avg_welfare,
            by_game_kind=dict(by_kind),
        )

    def _is_nash(self, game: Game, profile: dict[str, str]) -> bool:
        for player in game.players:
            current_payoff = self._get_payoffs(game, profile).get(player, 0.0)
            for alt_strategy in game.strategies.get(player, ()):
                if alt_strategy == profile[player]:
                    continue
                alt_profile = dict(profile)
                alt_profile[player] = alt_strategy
                alt_payoff = self._get_payoffs(game, alt_profile).get(player, 0.0)
                if alt_payoff > current_payoff:
                    return False
        return True

    def _is_pareto_optimal(self, game: Game, payoffs: dict[str, float]) -> bool:
        strategy_lists = [list(game.strategies.get(p, ())) for p in game.players]
        for profile in product(*strategy_lists):
            alt_map = dict(zip(game.players, profile))
            alt_payoffs = self._get_payoffs(game, alt_map)
            if all(alt_payoffs.get(p, 0) >= payoffs.get(p, 0) for p in game.players) and \
               any(alt_payoffs.get(p, 0) > payoffs.get(p, 0) for p in game.players):
                return False
        return True

    def _get_payoffs(self, game: Game, profile: dict[str, str]) -> dict[str, float]:
        strategies_tuple = tuple(profile.get(p, "") for p in game.players)
        for payoff in game.payoff_matrix:
            if payoff.strategies == strategies_tuple:
                return dict(zip(game.players, payoff.values))
        return {p: 0.0 for p in game.players}

    def _find_dominant_for_player(self, game: Game, player: str) -> str | None:
        strategies = list(game.strategies.get(player, ()))
        if not strategies:
            return None

        other_players = [p for p in game.players if p != player]
        other_strategy_lists = [list(game.strategies.get(p, ())) for p in other_players]

        for candidate in strategies:
            is_dominant = True
            for alt in strategies:
                if alt == candidate:
                    continue
                for other_profile in product(*other_strategy_lists):
                    profile_c = {player: candidate}
                    profile_a = {player: alt}
                    for p, s in zip(other_players, other_profile):
                        profile_c[p] = s
                        profile_a[p] = s
                    payoff_c = self._get_payoffs(game, profile_c).get(player, 0.0)
                    payoff_a = self._get_payoffs(game, profile_a).get(player, 0.0)
                    if payoff_c < payoff_a:
                        is_dominant = False
                        break
                if not is_dominant:
                    break
            if is_dominant:
                return candidate
        return None
