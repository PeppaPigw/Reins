"""Tests for morphogenesis engine."""

from __future__ import annotations

import pytest

from reins.morphogenesis import (
    AgentCell,
    CellState,
    MorphogenesisEngine,
    Signal,
    Specialization,
)


@pytest.fixture
def engine() -> MorphogenesisEngine:
    return MorphogenesisEngine(division_threshold=0.8, apoptosis_threshold=0.2, max_generation=5)


def test_spawn(engine):
    cell = engine.spawn()
    assert cell.state == CellState.UNDIFFERENTIATED
    assert cell.specialization == Specialization.GENERALIST
    assert cell.generation == 0


def test_spawn_with_specialization(engine):
    cell = engine.spawn(specialization=Specialization.PLANNER)
    assert cell.specialization == Specialization.PLANNER


def test_differentiate(engine):
    cell = engine.spawn()
    mature = engine.differentiate(cell.cell_id, Specialization.EXECUTOR)
    assert mature.state == CellState.MATURE
    assert mature.specialization == Specialization.EXECUTOR


def test_differentiate_nonexistent(engine):
    assert engine.differentiate("fake", Specialization.PLANNER) is None


def test_divide(engine):
    cell = engine.spawn()
    result = engine.divide(cell.cell_id)
    assert result is not None
    child1, child2 = result
    assert child1.generation == 1
    assert child2.generation == 1
    parent = engine.get_cell(cell.cell_id)
    assert parent.state == CellState.APOPTOSIS


def test_divide_max_generation(engine):
    cell = engine.spawn()
    current_id = cell.cell_id
    for _ in range(5):
        result = engine.divide(current_id)
        if result:
            current_id = result[0].cell_id
    last = engine.get_cell(current_id)
    assert engine.divide(current_id) is None


def test_merge(engine):
    a = engine.spawn(specialization=Specialization.PLANNER)
    b = engine.spawn(specialization=Specialization.EXECUTOR)
    engine.update_fitness(a.cell_id, 0.9)
    merged = engine.merge(a.cell_id, b.cell_id)
    assert merged is not None
    assert merged.state == CellState.MATURE
    assert engine.get_cell(a.cell_id).state == CellState.APOPTOSIS
    assert engine.get_cell(b.cell_id).state == CellState.APOPTOSIS


def test_merge_nonexistent(engine):
    a = engine.spawn()
    assert engine.merge(a.cell_id, "fake") is None


def test_update_fitness(engine):
    cell = engine.spawn()
    updated = engine.update_fitness(cell.cell_id, 0.9)
    assert updated.fitness == 0.9


def test_update_fitness_clamped(engine):
    cell = engine.spawn()
    updated = engine.update_fitness(cell.cell_id, 1.5)
    assert updated.fitness == 1.0


def test_update_load(engine):
    cell = engine.spawn()
    updated = engine.update_load(cell.cell_id, 0.7)
    assert updated.load == 0.7


def test_signal_apoptosis(engine):
    cell = engine.spawn()
    result = engine.signal(cell.cell_id, Signal.APOPTOSIS)
    assert result.state == CellState.APOPTOSIS


def test_auto_regulate_division(engine):
    cell = engine.spawn()
    engine.update_load(cell.cell_id, 0.9)
    events = engine.auto_regulate()
    assert len(events) >= 1
    assert engine.get_cell(cell.cell_id).state == CellState.APOPTOSIS


def test_auto_regulate_apoptosis(engine):
    cell = engine.spawn()
    engine.update_fitness(cell.cell_id, 0.1)
    engine.update_load(cell.cell_id, 0.0)
    events = engine.auto_regulate()
    assert len(events) >= 1
    assert engine.get_cell(cell.cell_id).state == CellState.APOPTOSIS


def test_get_active_cells(engine):
    c1 = engine.spawn()
    c2 = engine.spawn()
    engine.signal(c1.cell_id, Signal.APOPTOSIS)
    active = engine.get_active_cells()
    assert len(active) == 1
    assert active[0].cell_id == c2.cell_id


def test_get_cells_by_specialization(engine):
    engine.spawn(specialization=Specialization.PLANNER)
    engine.spawn(specialization=Specialization.PLANNER)
    engine.spawn(specialization=Specialization.EXECUTOR)
    planners = engine.get_cells_by_specialization(Specialization.PLANNER)
    assert len(planners) == 2


def test_stats_empty():
    e = MorphogenesisEngine()
    stats = e.get_stats()
    assert stats.total_cells == 0
    assert stats.active_cells == 0


def test_stats_with_data(engine):
    c1 = engine.spawn(specialization=Specialization.PLANNER)
    c2 = engine.spawn(specialization=Specialization.EXECUTOR)
    engine.update_fitness(c1.cell_id, 0.8)
    engine.update_fitness(c2.cell_id, 0.6)
    engine.update_load(c1.cell_id, 0.9)
    engine.auto_regulate()
    stats = engine.get_stats()
    assert stats.total_cells >= 2
    assert stats.total_divisions >= 1
