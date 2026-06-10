from __future__ import annotations

from collections import defaultdict

from reins.temporal_logic.types import (
    PropertyCheck,
    PropertyStatus,
    TemporalLogicStats,
    TemporalOp,
    TemporalProperty,
    Trace,
    TraceEvent,
)


class TemporalChecker:
    """LTL model checker for agent execution traces.

    Expresses and verifies temporal properties over finite traces:
    - ALWAYS(p): p holds at every step
    - EVENTUALLY(p): p holds at some step
    - NEVER(p): p never holds
    - NEXT(p): p holds at the next step
    - UNTIL(p, q): p holds until q becomes true
    - IMPLIES(p, q): whenever p holds, q holds at the same step

    Enables formal verification of agent behavior patterns like
    "approval always precedes production writes" or
    "every started task eventually completes."
    """

    def __init__(self) -> None:
        self._properties: dict[str, TemporalProperty] = {}
        self._checks: list[PropertyCheck] = []

    def define_property(self, name: str, operator: TemporalOp,
                        proposition: str, secondary: str = "",
                        description: str = "") -> TemporalProperty:
        prop = TemporalProperty(
            name=name, operator=operator,
            proposition=proposition, secondary=secondary,
            description=description,
        )
        self._properties[prop.property_id] = prop
        return prop

    def get_property(self, property_id: str) -> TemporalProperty | None:
        return self._properties.get(property_id)

    def check(self, property_id: str, trace: Trace) -> PropertyCheck:
        prop = self._properties.get(property_id)
        if not prop:
            check = PropertyCheck(
                property_id=property_id,
                status=PropertyStatus.UNKNOWN,
                witness="Property not found",
            )
            self._checks.append(check)
            return check

        if not trace.events:
            check = PropertyCheck(
                property_id=property_id,
                status=PropertyStatus.PENDING,
                witness="Empty trace",
                steps_checked=0,
            )
            self._checks.append(check)
            return check

        status, violated_at, witness = self._evaluate(prop, trace)

        check = PropertyCheck(
            property_id=property_id,
            status=status,
            violated_at_step=violated_at,
            witness=witness,
            steps_checked=len(trace.events),
        )
        self._checks.append(check)
        return check

    def check_all(self, trace: Trace) -> list[PropertyCheck]:
        return [self.check(pid, trace) for pid in self._properties]

    def check_online(self, property_id: str,
                     events_so_far: list[TraceEvent]) -> PropertyCheck:
        trace = Trace(events=events_so_far)
        prop = self._properties.get(property_id)
        if not prop:
            return PropertyCheck(property_id=property_id,
                                 status=PropertyStatus.UNKNOWN)

        status, violated_at, witness = self._evaluate(prop, trace)
        if status == PropertyStatus.SATISFIED and prop.operator == TemporalOp.EVENTUALLY:
            pass
        elif status == PropertyStatus.SATISFIED and prop.operator in (
            TemporalOp.ALWAYS, TemporalOp.NEVER
        ):
            status = PropertyStatus.PENDING

        check = PropertyCheck(
            property_id=property_id,
            status=status,
            violated_at_step=violated_at,
            witness=witness,
            steps_checked=len(events_so_far),
        )
        self._checks.append(check)
        return check

    def get_checks(self, property_id: str | None = None,
                   status: PropertyStatus | None = None) -> list[PropertyCheck]:
        checks = self._checks
        if property_id:
            checks = [c for c in checks if c.property_id == property_id]
        if status:
            checks = [c for c in checks if c.status == status]
        return checks

    def get_stats(self) -> TemporalLogicStats:
        by_op: dict[str, int] = defaultdict(int)
        for p in self._properties.values():
            by_op[p.operator.value] += 1

        by_status: dict[str, int] = defaultdict(int)
        satisfied = violated = pending = 0
        for c in self._checks:
            by_status[c.status.value] += 1
            if c.status == PropertyStatus.SATISFIED:
                satisfied += 1
            elif c.status == PropertyStatus.VIOLATED:
                violated += 1
            elif c.status == PropertyStatus.PENDING:
                pending += 1

        return TemporalLogicStats(
            total_properties=len(self._properties),
            total_checks=len(self._checks),
            satisfied=satisfied,
            violated=violated,
            pending=pending,
            by_operator=dict(by_op),
            by_status=dict(by_status),
        )

    def _evaluate(self, prop: TemporalProperty,
                  trace: Trace) -> tuple[PropertyStatus, int | None, str]:
        match prop.operator:
            case TemporalOp.ALWAYS:
                return self._check_always(prop.proposition, trace)
            case TemporalOp.EVENTUALLY:
                return self._check_eventually(prop.proposition, trace)
            case TemporalOp.NEVER:
                return self._check_never(prop.proposition, trace)
            case TemporalOp.NEXT:
                return self._check_next(prop.proposition, trace)
            case TemporalOp.UNTIL:
                return self._check_until(prop.proposition, prop.secondary, trace)
            case TemporalOp.IMPLIES:
                return self._check_implies(prop.proposition, prop.secondary, trace)

    def _check_always(self, prop: str,
                      trace: Trace) -> tuple[PropertyStatus, int | None, str]:
        for event in trace.events:
            if prop not in event.propositions:
                return (PropertyStatus.VIOLATED, event.step,
                        f"'{prop}' not held at step {event.step}")
        return (PropertyStatus.SATISFIED, None,
                f"'{prop}' held at all {len(trace.events)} steps")

    def _check_eventually(self, prop: str,
                          trace: Trace) -> tuple[PropertyStatus, int | None, str]:
        for event in trace.events:
            if prop in event.propositions:
                return (PropertyStatus.SATISFIED, None,
                        f"'{prop}' satisfied at step {event.step}")
        return (PropertyStatus.VIOLATED, None,
                f"'{prop}' never became true in {len(trace.events)} steps")

    def _check_never(self, prop: str,
                     trace: Trace) -> tuple[PropertyStatus, int | None, str]:
        for event in trace.events:
            if prop in event.propositions:
                return (PropertyStatus.VIOLATED, event.step,
                        f"'{prop}' unexpectedly held at step {event.step}")
        return (PropertyStatus.SATISFIED, None,
                f"'{prop}' never held (as required)")

    def _check_next(self, prop: str,
                    trace: Trace) -> tuple[PropertyStatus, int | None, str]:
        if len(trace.events) < 2:
            return (PropertyStatus.PENDING, None, "Need at least 2 events for NEXT")
        second = trace.events[1]
        if prop in second.propositions:
            return (PropertyStatus.SATISFIED, None,
                    f"'{prop}' holds at step 1")
        return (PropertyStatus.VIOLATED, 1,
                f"'{prop}' does not hold at step 1")

    def _check_until(self, p: str, q: str,
                     trace: Trace) -> tuple[PropertyStatus, int | None, str]:
        for event in trace.events:
            if q in event.propositions:
                return (PropertyStatus.SATISFIED, None,
                        f"'{q}' became true at step {event.step}, "
                        f"'{p}' held until then")
            if p not in event.propositions:
                return (PropertyStatus.VIOLATED, event.step,
                        f"'{p}' failed at step {event.step} before '{q}' became true")
        return (PropertyStatus.VIOLATED, None,
                f"'{q}' never became true")

    def _check_implies(self, p: str, q: str,
                       trace: Trace) -> tuple[PropertyStatus, int | None, str]:
        for event in trace.events:
            if p in event.propositions and q not in event.propositions:
                return (PropertyStatus.VIOLATED, event.step,
                        f"'{p}' held but '{q}' did not at step {event.step}")
        return (PropertyStatus.SATISFIED, None,
                f"'{p}' → '{q}' held at all steps")
