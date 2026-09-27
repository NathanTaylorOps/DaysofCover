"""Resolving a scenario's named disruptions against a real network, day by day.

Session 22's review of the finished Stage 1 engine found two schema
types that were fully modelled and referentially validated --
:class:`daysofcover.models.scenario.Disruption` and
:class:`daysofcover.models.network.HazardGroup` -- but never once read
by the engine itself. The order-pausing mechanic that "validated case
4" (:mod:`daysofcover.engine.disruption`) is a disconnected single-node
script driven by a random two-state Markov sampler, which answers a
different question (an *unpredictable, recurring* outage, matched
against stockpyl's own ``DisruptionProcess`` tutorial) from the one a
named :class:`Disruption` asks: a specific, dated event within one
scenario, with an explicit start day, severity, duration and recovery
ramp. This module is the second question's answer, wired into the real
multi-node engine rather than a throwaway script.

A :class:`Disruption` names one ``element_id`` -- a node or a lane, per
:class:`daysofcover.models.network.Network`'s own referential validator
(the only two id spaces it checks a hazard membership's ``element_id``
against). The build plan itself says how a node-level disruption
behaves: "a closed port stops every lane through it". :meth:`Disruption
State.from_scenario` resolves that cascade once, at construction --
every disruption naming a node is filed under that node's own id *and*
under every lane whose ``origin_id`` or ``destination_id`` is that
node -- so a caller never special-cases "is this id a node or a lane";
:meth:`DisruptionState.severity_at` answers the same way for either.

Severity follows exactly the shape :mod:`daysofcover.engine.ramp`
already validated against case 12's lost-sales bounds: zero before
``start_day``, a flat ``severity_fraction`` for ``duration_days``, then
a linear recovery to zero over ``ramp_days`` -- read here as fraction
of capacity *lost*, where ``ramp.py`` reads the same shape as fraction
of capacity *restored*. Two disruptions can never name the same
element by coincidence and partially cancel each other out: when more
than one disruption touches an element on the same day (deliberately
rare, but the schema allows a hazard group's members to overlap), the
worse of the two applies, not their sum or their average.

Deliberately still binary, not proportional: a lane or the port node at
its destination is treated as fully able to receive whatever already
left port only when ``severity_at`` is strictly below 1.0 for that
element right now. A fractional severity (a rolling partial closure,
say 0.5) throttles *new* capacity for orders placed from today, via
the same ``severity_at`` value, but does not hold back cargo already
in transit -- the build plan's own language for the closed-port case is
binary ("a closed port stops every lane through it"), and a template
already fractional and time-varying (the stevedore rolling-closure
example) is expected to be modelled as ordinary severity change over
several named disruptions, not as a second, partial-release mechanic
on top. :mod:`daysofcover.engine.daily_step` is the caller that decides
whether to skip a day's :meth:`daysofcover.engine.shipments.NetworkShip
ments.receive` for a fully (severity 1.0) closed lane -- this module
only answers "how severe, right now", not what a caller does with that
number.
"""

from __future__ import annotations

from dataclasses import dataclass

from daysofcover.models.network import Network
from daysofcover.models.scenario import Disruption, Scenario


def _severity_on_day(disruption: Disruption, day: int) -> float:
    """One disruption's own severity fraction lost on ``day``.

    The mirror image of :func:`daysofcover.engine.ramp.linear_ramp_
    capacity`'s validated shape: zero before ``start_day``; a flat
    ``severity_fraction`` for the ``duration_days`` after that; then,
    if ``ramp_days`` is positive, a linear recovery to zero over
    ``ramp_days`` more (the first day of recovery sits at
    ``severity_fraction * (ramp_days - 1) / ramp_days``, exactly as
    ``linear_ramp_capacity``'s first day back sits at ``1/ramp_days`` of
    the way to full, just read as severity remaining instead of
    capacity restored). ``ramp_days == 0`` (the schema's default) means
    an instant recovery: full severity through the last day of
    ``duration_days``, zero the day after.
    """
    if day < disruption.start_day:
        return 0.0

    elapsed = day - disruption.start_day
    if elapsed < disruption.duration_days:
        return disruption.severity_fraction

    if disruption.ramp_days <= 0:
        return 0.0

    days_since_recovery_start = elapsed - disruption.duration_days
    if days_since_recovery_start >= disruption.ramp_days:
        return 0.0

    fraction_restored = (days_since_recovery_start + 1) / disruption.ramp_days
    return disruption.severity_fraction * (1.0 - fraction_restored)


@dataclass
class DisruptionState:
    """A scenario's disruptions, resolved against one network's real ids.

    Built once per scenario (or per replication, if a future session
    makes any of this random -- it currently is not), then queried by
    day. See the module docstring for the node-to-lane cascade and the
    binary-hold-vs-proportional-capacity design choice.
    """

    disruptions_by_element: dict[str, tuple[Disruption, ...]]

    @classmethod
    def from_scenario(cls, scenario: Scenario, *, network: Network) -> DisruptionState:
        """Resolve ``scenario.disruptions`` against ``network``'s real node and lane ids.

        Raises :class:`ValueError` for a disruption naming neither a
        known node nor a known lane -- the same check
        :class:`daysofcover.models.network.Network`'s own hazard-group
        validator already makes for ``HazardGroupMember``, applied here
        too since a :class:`Disruption` is never run through that
        validator itself (it lives on a :class:`daysofcover.models.
        scenario.Scenario`, not on the network).
        """
        node_ids = {node.id for node in network.nodes}
        lane_ids = {lane.id for lane in network.lanes}

        lanes_touching_node: dict[str, list[str]] = {}
        for lane in network.lanes:
            lanes_touching_node.setdefault(lane.origin_id, []).append(lane.id)
            lanes_touching_node.setdefault(lane.destination_id, []).append(lane.id)

        by_element: dict[str, list[Disruption]] = {}
        for disruption in scenario.disruptions:
            element_id = disruption.element_id
            if element_id in lane_ids:
                by_element.setdefault(element_id, []).append(disruption)
            elif element_id in node_ids:
                by_element.setdefault(element_id, []).append(disruption)
                for lane_id in lanes_touching_node.get(element_id, []):
                    by_element.setdefault(lane_id, []).append(disruption)
            else:
                raise ValueError(
                    f"disruption element_id {element_id!r} is not a known node or lane id"
                )

        return cls(disruptions_by_element={k: tuple(v) for k, v in by_element.items()})

    def severity_at(self, *, element_id: str, day: int) -> float:
        """The worst severity in effect for ``element_id`` on ``day``, or 0.0 if none applies."""
        disruptions = self.disruptions_by_element.get(element_id, ())
        if not disruptions:
            return 0.0
        return max(_severity_on_day(disruption, day) for disruption in disruptions)

    def is_fully_down(self, *, element_id: str, day: int) -> bool:
        """Whether ``element_id`` is completely down right now (severity exactly 1.0).

        The threshold :mod:`daysofcover.engine.daily_step` uses to
        decide whether to hold back cargo already in transit -- see the
        module docstring's binary-vs-proportional design note.
        """
        return self.severity_at(element_id=element_id, day=day) >= 1.0
