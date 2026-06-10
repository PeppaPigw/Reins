"""Tests for Contract Net Protocol engine."""

from __future__ import annotations

import pytest

from reins.contract_net import (
    Bid,
    BidStatus,
    Contract,
    ContractNetEngine,
    SelectionStrategy,
    TaskAnnouncement,
    TaskStatus,
)


@pytest.fixture
def engine() -> ContractNetEngine:
    return ContractNetEngine(strategy=SelectionStrategy.BEST_VALUE)


def test_announce_task(engine):
    task = engine.announce_task("manager-1", "Build feature X")
    assert task.manager_id == "manager-1"
    assert task.status == TaskStatus.BIDDING


def test_submit_bid(engine):
    task = engine.announce_task("m", "task")
    bid = engine.submit_bid(task.task_id, "worker-1", cost=10.0, quality_score=0.8)
    assert bid is not None
    assert bid.bidder_id == "worker-1"
    assert bid.cost == 10.0


def test_submit_bid_nonexistent_task(engine):
    assert engine.submit_bid("fake", "w", cost=5.0) is None


def test_submit_bid_over_budget(engine):
    task = engine.announce_task("m", "task", max_cost=50.0)
    bid = engine.submit_bid(task.task_id, "w", cost=100.0)
    assert bid is None


def test_award_contract(engine):
    task = engine.announce_task("m", "task")
    engine.submit_bid(task.task_id, "w1", cost=10.0, quality_score=0.9)
    engine.submit_bid(task.task_id, "w2", cost=20.0, quality_score=0.7)
    contract = engine.award_contract(task.task_id)
    assert contract is not None
    assert contract.contractor_id in ("w1", "w2")


def test_award_no_bids(engine):
    task = engine.announce_task("m", "task")
    assert engine.award_contract(task.task_id) is None


def test_task_status_after_award(engine):
    task = engine.announce_task("m", "task")
    engine.submit_bid(task.task_id, "w", cost=5.0)
    engine.award_contract(task.task_id)
    updated = engine.get_task(task.task_id)
    assert updated.status == TaskStatus.AWARDED


def test_complete_task_success(engine):
    task = engine.announce_task("m", "task")
    engine.submit_bid(task.task_id, "w", cost=5.0)
    engine.award_contract(task.task_id)
    result = engine.complete_task(task.task_id, success=True)
    assert result.status == TaskStatus.COMPLETED


def test_complete_task_failure(engine):
    task = engine.announce_task("m", "task")
    engine.submit_bid(task.task_id, "w", cost=5.0)
    engine.award_contract(task.task_id)
    result = engine.complete_task(task.task_id, success=False)
    assert result.status == TaskStatus.FAILED


def test_reputation_increases_on_success(engine):
    task = engine.announce_task("m", "task")
    engine.submit_bid(task.task_id, "reliable", cost=5.0)
    engine.award_contract(task.task_id)
    before = engine.get_reputation("reliable")
    engine.complete_task(task.task_id, success=True)
    after = engine.get_reputation("reliable")
    assert after > before


def test_reputation_decreases_on_failure(engine):
    task = engine.announce_task("m", "task")
    engine.submit_bid(task.task_id, "flaky", cost=5.0)
    engine.award_contract(task.task_id)
    before = engine.get_reputation("flaky")
    engine.complete_task(task.task_id, success=False)
    after = engine.get_reputation("flaky")
    assert after < before


def test_lowest_cost_strategy():
    e = ContractNetEngine(strategy=SelectionStrategy.LOWEST_COST)
    task = e.announce_task("m", "task")
    e.submit_bid(task.task_id, "expensive", cost=100.0)
    e.submit_bid(task.task_id, "cheap", cost=5.0)
    contract = e.award_contract(task.task_id)
    assert contract.contractor_id == "cheap"


def test_highest_quality_strategy():
    e = ContractNetEngine(strategy=SelectionStrategy.HIGHEST_QUALITY)
    task = e.announce_task("m", "task")
    e.submit_bid(task.task_id, "low_q", cost=5.0, quality_score=0.3)
    e.submit_bid(task.task_id, "high_q", cost=50.0, quality_score=0.95)
    contract = e.award_contract(task.task_id)
    assert contract.contractor_id == "high_q"


def test_fastest_strategy():
    e = ContractNetEngine(strategy=SelectionStrategy.FASTEST)
    task = e.announce_task("m", "task")
    e.submit_bid(task.task_id, "slow", estimated_duration_ms=10000.0)
    e.submit_bid(task.task_id, "fast", estimated_duration_ms=100.0)
    contract = e.award_contract(task.task_id)
    assert contract.contractor_id == "fast"


def test_get_open_tasks(engine):
    engine.announce_task("m", "open1")
    engine.announce_task("m", "open2")
    t3 = engine.announce_task("m", "will_close")
    engine.submit_bid(t3.task_id, "w", cost=1.0)
    engine.award_contract(t3.task_id)
    open_tasks = engine.get_open_tasks()
    assert len(open_tasks) == 2


def test_get_bids(engine):
    task = engine.announce_task("m", "task")
    engine.submit_bid(task.task_id, "w1", cost=10.0)
    engine.submit_bid(task.task_id, "w2", cost=20.0)
    bids = engine.get_bids(task.task_id)
    assert len(bids) == 2


def test_bid_status_after_award(engine):
    task = engine.announce_task("m", "task")
    engine.submit_bid(task.task_id, "winner", cost=5.0, quality_score=0.9)
    engine.submit_bid(task.task_id, "loser", cost=50.0, quality_score=0.1)
    engine.award_contract(task.task_id)
    bids = engine.get_bids(task.task_id)
    accepted = [b for b in bids if b.status == BidStatus.ACCEPTED]
    rejected = [b for b in bids if b.status == BidStatus.REJECTED]
    assert len(accepted) == 1
    assert len(rejected) == 1


def test_stats_empty():
    e = ContractNetEngine()
    stats = e.get_stats()
    assert stats.total_announcements == 0
    assert stats.total_bids == 0


def test_stats_with_data(engine):
    task = engine.announce_task("m", "task")
    engine.submit_bid(task.task_id, "w1", cost=10.0)
    engine.submit_bid(task.task_id, "w2", cost=20.0)
    engine.award_contract(task.task_id)
    stats = engine.get_stats()
    assert stats.total_announcements == 1
    assert stats.total_bids == 2
    assert stats.total_contracts == 1
    assert stats.avg_bids_per_task == 2.0
