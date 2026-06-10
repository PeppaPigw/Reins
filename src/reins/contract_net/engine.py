from __future__ import annotations

from collections import defaultdict

from reins.contract_net.types import (
    Bid,
    BidStatus,
    Contract,
    ContractNetStats,
    SelectionStrategy,
    TaskAnnouncement,
    TaskStatus,
)


class ContractNetEngine:
    """Contract Net Protocol for multi-agent task allocation.

    Implements the FIPA Contract Net interaction protocol where a manager
    announces tasks, contractors submit bids, and the manager awards
    contracts based on configurable selection strategies.
    """

    def __init__(self, strategy: SelectionStrategy = SelectionStrategy.BEST_VALUE,
                 max_bids_per_task: int = 10) -> None:
        self._strategy = strategy
        self._max_bids = max_bids_per_task
        self._tasks: dict[str, TaskAnnouncement] = {}
        self._bids: dict[str, list[Bid]] = defaultdict(list)
        self._contracts: dict[str, Contract] = {}
        self._reputation: dict[str, float] = defaultdict(lambda: 0.5)

    def announce_task(self, manager_id: str, description: str,
                      requirements: dict | None = None,
                      deadline_ms: float = 0.0,
                      max_cost: float = 0.0) -> TaskAnnouncement:
        task = TaskAnnouncement(
            manager_id=manager_id, description=description,
            requirements=requirements or {},
            deadline_ms=deadline_ms, max_cost=max_cost,
            status=TaskStatus.BIDDING,
        )
        self._tasks[task.task_id] = task
        return task

    def submit_bid(self, task_id: str, bidder_id: str,
                   cost: float = 0.0, estimated_duration_ms: float = 0.0,
                   quality_score: float = 0.5,
                   capabilities: list[str] | None = None) -> Bid | None:
        task = self._tasks.get(task_id)
        if not task or task.status != TaskStatus.BIDDING:
            return None

        if len(self._bids[task_id]) >= self._max_bids:
            return None

        if task.max_cost > 0 and cost > task.max_cost:
            return None

        bid = Bid(
            task_id=task_id, bidder_id=bidder_id,
            cost=cost, estimated_duration_ms=estimated_duration_ms,
            quality_score=quality_score,
            capabilities=tuple(capabilities or []),
        )
        self._bids[task_id].append(bid)
        return bid

    def award_contract(self, task_id: str) -> Contract | None:
        task = self._tasks.get(task_id)
        if not task or task.status != TaskStatus.BIDDING:
            return None

        bids = self._bids.get(task_id, [])
        if not bids:
            return None

        winner = self._select_winner(bids)
        if not winner:
            return None

        for bid in bids:
            if bid.bid_id == winner.bid_id:
                updated_bid = Bid(
                    bid_id=bid.bid_id, task_id=bid.task_id,
                    bidder_id=bid.bidder_id, cost=bid.cost,
                    estimated_duration_ms=bid.estimated_duration_ms,
                    quality_score=bid.quality_score,
                    capabilities=bid.capabilities,
                    status=BidStatus.ACCEPTED,
                    submitted_at=bid.submitted_at,
                )
                self._bids[task_id] = [
                    updated_bid if b.bid_id == bid.bid_id else
                    Bid(bid_id=b.bid_id, task_id=b.task_id,
                        bidder_id=b.bidder_id, cost=b.cost,
                        estimated_duration_ms=b.estimated_duration_ms,
                        quality_score=b.quality_score,
                        capabilities=b.capabilities,
                        status=BidStatus.REJECTED,
                        submitted_at=b.submitted_at)
                    for b in bids
                ]

        contract = Contract(
            task_id=task_id,
            manager_id=task.manager_id,
            contractor_id=winner.bidder_id,
            agreed_cost=winner.cost,
            agreed_duration_ms=winner.estimated_duration_ms,
        )
        self._contracts[task_id] = contract

        updated_task = TaskAnnouncement(
            task_id=task.task_id, manager_id=task.manager_id,
            description=task.description, requirements=task.requirements,
            deadline_ms=task.deadline_ms, max_cost=task.max_cost,
            status=TaskStatus.AWARDED, created_at=task.created_at,
        )
        self._tasks[task_id] = updated_task
        return contract

    def complete_task(self, task_id: str, success: bool = True) -> TaskAnnouncement | None:
        task = self._tasks.get(task_id)
        if not task or task.status != TaskStatus.AWARDED:
            return None

        new_status = TaskStatus.COMPLETED if success else TaskStatus.FAILED
        updated = TaskAnnouncement(
            task_id=task.task_id, manager_id=task.manager_id,
            description=task.description, requirements=task.requirements,
            deadline_ms=task.deadline_ms, max_cost=task.max_cost,
            status=new_status, created_at=task.created_at,
        )
        self._tasks[task_id] = updated

        contract = self._contracts.get(task_id)
        if contract:
            rep = self._reputation[contract.contractor_id]
            if success:
                self._reputation[contract.contractor_id] = min(1.0, rep + 0.05)
            else:
                self._reputation[contract.contractor_id] = max(0.0, rep - 0.1)

        return updated

    def get_task(self, task_id: str) -> TaskAnnouncement | None:
        return self._tasks.get(task_id)

    def get_bids(self, task_id: str) -> list[Bid]:
        return self._bids.get(task_id, [])

    def get_contract(self, task_id: str) -> Contract | None:
        return self._contracts.get(task_id)

    def get_reputation(self, agent_id: str) -> float:
        return self._reputation[agent_id]

    def get_open_tasks(self) -> list[TaskAnnouncement]:
        return [t for t in self._tasks.values() if t.status == TaskStatus.BIDDING]

    def get_stats(self) -> ContractNetStats:
        by_status: dict[str, int] = defaultdict(int)
        for t in self._tasks.values():
            by_status[t.status.value] += 1

        total_bids = sum(len(bs) for bs in self._bids.values())
        tasks_with_bids = sum(1 for bs in self._bids.values() if bs)
        avg_bids = total_bids / tasks_with_bids if tasks_with_bids else 0.0

        costs = [c.agreed_cost for c in self._contracts.values()]
        avg_cost = sum(costs) / len(costs) if costs else 0.0

        return ContractNetStats(
            total_announcements=len(self._tasks),
            total_bids=total_bids,
            total_contracts=len(self._contracts),
            completed=by_status.get("completed", 0),
            failed=by_status.get("failed", 0),
            avg_bids_per_task=avg_bids,
            avg_cost=avg_cost,
            by_status=dict(by_status),
        )

    def _select_winner(self, bids: list[Bid]) -> Bid | None:
        if not bids:
            return None

        if self._strategy == SelectionStrategy.LOWEST_COST:
            return min(bids, key=lambda b: b.cost)
        elif self._strategy == SelectionStrategy.HIGHEST_QUALITY:
            return max(bids, key=lambda b: b.quality_score)
        elif self._strategy == SelectionStrategy.FASTEST:
            return min(bids, key=lambda b: b.estimated_duration_ms)
        elif self._strategy == SelectionStrategy.REPUTATION:
            return max(bids, key=lambda b: self._reputation[b.bidder_id])
        else:
            return max(bids, key=lambda b: self._compute_value(b))

    def _compute_value(self, bid: Bid) -> float:
        cost_norm = 1.0 / (1.0 + bid.cost) if bid.cost > 0 else 1.0
        quality = bid.quality_score
        speed = 1.0 / (1.0 + bid.estimated_duration_ms / 1000.0)
        rep = self._reputation[bid.bidder_id]
        return 0.3 * cost_norm + 0.3 * quality + 0.2 * speed + 0.2 * rep
