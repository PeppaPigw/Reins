from __future__ import annotations

from collections import defaultdict

from reins.morphogenesis.types import (
    AgentCell,
    CellState,
    MorphEvent,
    MorphogenesisStats,
    Signal,
    Specialization,
)


class MorphogenesisEngine:
    """Self-organizing agent architecture inspired by biological development.

    Agents (cells) can grow, divide, specialize, merge, and undergo
    programmed death based on fitness signals and workload patterns.
    Enables adaptive scaling without centralized control.
    """

    def __init__(self, division_threshold: float = 0.8,
                 apoptosis_threshold: float = 0.2,
                 max_generation: int = 5) -> None:
        self._division_threshold = division_threshold
        self._apoptosis_threshold = apoptosis_threshold
        self._max_generation = max_generation
        self._cells: dict[str, AgentCell] = {}
        self._events: list[MorphEvent] = []

    def spawn(self, specialization: Specialization = Specialization.GENERALIST,
              parent_id: str = "") -> AgentCell:
        generation = 0
        if parent_id and parent_id in self._cells:
            generation = self._cells[parent_id].generation + 1

        cell = AgentCell(
            state=CellState.UNDIFFERENTIATED,
            specialization=specialization,
            generation=generation,
            parent_id=parent_id,
        )
        self._cells[cell.cell_id] = cell
        return cell

    def differentiate(self, cell_id: str,
                      specialization: Specialization) -> AgentCell | None:
        cell = self._cells.get(cell_id)
        if not cell or cell.state == CellState.APOPTOSIS:
            return None

        updated = AgentCell(
            cell_id=cell.cell_id, state=CellState.MATURE,
            specialization=specialization, fitness=cell.fitness,
            load=cell.load, generation=cell.generation,
            parent_id=cell.parent_id, metadata=cell.metadata,
            created_at=cell.created_at,
        )
        self._cells[cell_id] = updated
        self._events.append(MorphEvent(
            cell_id=cell_id, signal=Signal.DIFFERENTIATE,
            result=f"Specialized as {specialization.value}",
        ))
        return updated

    def divide(self, cell_id: str) -> tuple[AgentCell, AgentCell] | None:
        cell = self._cells.get(cell_id)
        if not cell or cell.state == CellState.APOPTOSIS:
            return None
        if cell.generation >= self._max_generation:
            return None

        child1 = self.spawn(specialization=cell.specialization, parent_id=cell_id)
        child2 = self.spawn(specialization=cell.specialization, parent_id=cell_id)

        updated_parent = AgentCell(
            cell_id=cell.cell_id, state=CellState.APOPTOSIS,
            specialization=cell.specialization, fitness=0.0,
            load=0.0, generation=cell.generation,
            parent_id=cell.parent_id, metadata=cell.metadata,
            created_at=cell.created_at,
        )
        self._cells[cell_id] = updated_parent

        self._events.append(MorphEvent(
            cell_id=cell_id, signal=Signal.DIVIDE,
            result=f"Split into {child1.cell_id} and {child2.cell_id}",
        ))
        return (child1, child2)

    def merge(self, cell_id_a: str, cell_id_b: str) -> AgentCell | None:
        a = self._cells.get(cell_id_a)
        b = self._cells.get(cell_id_b)
        if not a or not b:
            return None
        if a.state == CellState.APOPTOSIS or b.state == CellState.APOPTOSIS:
            return None

        merged_fitness = (a.fitness + b.fitness) / 2
        spec = a.specialization if a.fitness >= b.fitness else b.specialization
        gen = max(a.generation, b.generation)

        merged = AgentCell(
            state=CellState.MATURE,
            specialization=spec,
            fitness=merged_fitness,
            load=(a.load + b.load) / 2,
            generation=gen,
            parent_id=cell_id_a,
        )
        self._cells[merged.cell_id] = merged

        for cid in (cell_id_a, cell_id_b):
            old = self._cells[cid]
            self._cells[cid] = AgentCell(
                cell_id=old.cell_id, state=CellState.APOPTOSIS,
                specialization=old.specialization, fitness=0.0,
                load=0.0, generation=old.generation,
                parent_id=old.parent_id, metadata=old.metadata,
                created_at=old.created_at,
            )

        self._events.append(MorphEvent(
            cell_id=merged.cell_id, signal=Signal.MERGE,
            result=f"Merged from {cell_id_a} and {cell_id_b}",
        ))
        return merged

    def update_fitness(self, cell_id: str, fitness: float) -> AgentCell | None:
        cell = self._cells.get(cell_id)
        if not cell or cell.state == CellState.APOPTOSIS:
            return None

        fitness = max(0.0, min(1.0, fitness))
        updated = AgentCell(
            cell_id=cell.cell_id, state=cell.state,
            specialization=cell.specialization, fitness=fitness,
            load=cell.load, generation=cell.generation,
            parent_id=cell.parent_id, metadata=cell.metadata,
            created_at=cell.created_at,
        )
        self._cells[cell_id] = updated
        return updated

    def update_load(self, cell_id: str, load: float) -> AgentCell | None:
        cell = self._cells.get(cell_id)
        if not cell or cell.state == CellState.APOPTOSIS:
            return None

        load = max(0.0, min(1.0, load))
        updated = AgentCell(
            cell_id=cell.cell_id, state=cell.state,
            specialization=cell.specialization, fitness=cell.fitness,
            load=load, generation=cell.generation,
            parent_id=cell.parent_id, metadata=cell.metadata,
            created_at=cell.created_at,
        )
        self._cells[cell_id] = updated
        return updated

    def signal(self, cell_id: str, sig: Signal) -> AgentCell | None:
        cell = self._cells.get(cell_id)
        if not cell:
            return None

        if sig == Signal.APOPTOSIS:
            updated = AgentCell(
                cell_id=cell.cell_id, state=CellState.APOPTOSIS,
                specialization=cell.specialization, fitness=0.0,
                load=0.0, generation=cell.generation,
                parent_id=cell.parent_id, metadata=cell.metadata,
                created_at=cell.created_at,
            )
            self._cells[cell_id] = updated
            self._events.append(MorphEvent(cell_id=cell_id, signal=sig, result="Cell died"))
            return updated

        self._events.append(MorphEvent(cell_id=cell_id, signal=sig))
        return cell

    def auto_regulate(self) -> list[MorphEvent]:
        events = []
        for cell_id, cell in list(self._cells.items()):
            if cell.state == CellState.APOPTOSIS:
                continue

            if cell.load >= self._division_threshold and cell.generation < self._max_generation:
                result = self.divide(cell_id)
                if result:
                    events.append(self._events[-1])

            elif cell.fitness <= self._apoptosis_threshold and cell.load < 0.1:
                self.signal(cell_id, Signal.APOPTOSIS)
                events.append(self._events[-1])

        return events

    def get_cell(self, cell_id: str) -> AgentCell | None:
        return self._cells.get(cell_id)

    def get_active_cells(self) -> list[AgentCell]:
        return [c for c in self._cells.values() if c.state != CellState.APOPTOSIS]

    def get_cells_by_specialization(self, spec: Specialization) -> list[AgentCell]:
        return [c for c in self.get_active_cells() if c.specialization == spec]

    def get_stats(self) -> MorphogenesisStats:
        by_state: dict[str, int] = defaultdict(int)
        by_spec: dict[str, int] = defaultdict(int)
        fitnesses = []
        loads = []
        max_gen = 0

        for cell in self._cells.values():
            by_state[cell.state.value] += 1
            if cell.state != CellState.APOPTOSIS:
                by_spec[cell.specialization.value] += 1
                fitnesses.append(cell.fitness)
                loads.append(cell.load)
                max_gen = max(max_gen, cell.generation)

        divisions = sum(1 for e in self._events if e.signal == Signal.DIVIDE)
        merges = sum(1 for e in self._events if e.signal == Signal.MERGE)
        active = sum(1 for c in self._cells.values() if c.state != CellState.APOPTOSIS)

        return MorphogenesisStats(
            total_cells=len(self._cells),
            active_cells=active,
            by_state=dict(by_state),
            by_specialization=dict(by_spec),
            avg_fitness=sum(fitnesses) / len(fitnesses) if fitnesses else 0.0,
            avg_load=sum(loads) / len(loads) if loads else 0.0,
            total_divisions=divisions,
            total_merges=merges,
            max_generation=max_gen,
        )
