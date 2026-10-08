"""Track in-transit shipments by lane and commodity.

Each shipment records dispatch and arrival timing. Independent lognormal
lead-time draws determine arrival dates, subject to the lane's crossing
policy. FIFO lanes prevent a later shipment from arriving before an
earlier shipment of the same commodity; crossing-enabled lanes permit
arrival order to differ from dispatch order.

Lane shipment records also enforce the configured weekly capacity and
minimum order quantity. Capacity consumption is tracked centrally by the
lane so all callers share the same limit. The separate
`cap_order_quantity` helper determines whether a proposed shipment can
be placed without creating zero-quantity or sub-MOQ orders.
"""

from __future__ import annotations

import heapq
import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from daysofcover.models.network import Lane, Network


def _draw_lead_time_days(*, median_days: float, sigma: float, rng: np.random.Generator) -> int:
    """One shipment's own lognormal lead time, in whole days (at least 1).

    ``median_days`` and ``sigma`` are exactly the schema's
    :class:`daysofcover.models.network.Lane` fields, so no conversion to
    the underlying normal's mean/sigma is needed beyond ``mu =
    ln(median_days)`` -- the same relationship
    :func:`daysofcover.engine.pipeline.lognormal_mean_days` uses for the
    distribution's mean.
    """
    mu = math.log(median_days)
    lead_time = rng.lognormal(mean=mu, sigma=sigma)
    return max(1, round(lead_time))


def cap_order_quantity(
    *, desired_quantity: float, moq: float | None, capacity_remaining: float
) -> float:
    """How much of ``desired_quantity`` can actually be ordered right now.

    ``moq`` (minimum order quantity, when the lane's supplier has one) is
    rounded *up* to, never down from -- a desired order below the MOQ
    still becomes a full MOQ-sized order, matching how a real supplier
    would not ship less than their minimum. ``capacity_remaining`` (the
    lane's own weekly cap, already netted for whatever it has shipped
    this week -- see :meth:`LaneShipments.capacity_remaining`) is then
    applied as a hard ceiling. If that ceiling cuts the order back below
    the MOQ, the whole order is deferred to zero rather than placed
    partially -- a supplier who requires an MOQ will not ship a
    sub-MOQ quantity just because that is all this week's capacity
    allows; the rest of the desired order waits for a future week's
    capacity instead of arriving split into a MOQ-violating partial
    shipment.
    """
    if desired_quantity <= 0:
        return 0.0

    required = desired_quantity if moq is None else max(desired_quantity, moq)
    capped = min(required, capacity_remaining)
    if moq is not None and capped < moq:
        return 0.0
    return capped


def _fifo_arrival_day(candidate_arrival_day: int, previous_arrival_day: int | None) -> int:
    """FIFO enforcement, in isolation from any random draw.

    A shipment can never be recorded as arriving before the one placed
    ahead of it on the same lane and part -- ``previous_arrival_day`` is
    ``None`` only for the first shipment on a lane and part, which always
    arrives on its own candidate day.
    """
    if previous_arrival_day is None:
        return candidate_arrival_day
    return max(candidate_arrival_day, previous_arrival_day)


@dataclass
class LaneShipments:
    """In-transit shipments for one lane, keyed by part id.

    A FIFO part's shipments live in a deque, in placement order, each
    entry an ``(arrival_day, quantity)`` pair with ``arrival_day``
    already FIFO-adjusted. A crossing-allowed part's shipments live in a
    min-heap ordered by arrival day, each entry ``(arrival_day, sequence,
    quantity)`` -- ``sequence`` is an insertion counter, not a rule the
    build plan asks for, but it keeps two shipments that land on the very
    same day in a fixed, reproducible order rather than an arbitrary one
    that would depend on how their quantities happen to compare.
    """

    lane: Lane
    _fifo: dict[str, deque[tuple[int, float]]] = field(default_factory=dict)
    _heap: dict[str, list[tuple[int, int, float]]] = field(default_factory=dict)
    _sequence: int = 0
    _capacity_week_start: int | None = None
    _capacity_used_this_week: float = 0.0

    def capacity_remaining(self, *, current_day: int) -> float:
        """This lane's unused ``capacity_per_week`` for the week containing ``current_day``.

        Weeks are fixed 7-day blocks anchored at day 0 (``(current_day //
        7) * 7``), not a rolling 7 days from each order -- the same
        simple, deterministic week boundary the rest of the engine uses
        for anything periodic (e.g. session 19's ``review_period_days``).
        Crossing into a new week resets the used-this-week counter before
        computing what remains, so this method is always safe to call
        just to find out how much room is left, not only right before
        shipping.
        """
        week_start = (current_day // 7) * 7
        if week_start != self._capacity_week_start:
            self._capacity_week_start = week_start
            self._capacity_used_this_week = 0.0
        return max(0.0, self.lane.capacity_per_week - self._capacity_used_this_week)

    def ship(
        self, *, part_id: str, quantity: float, order_day: int, rng: np.random.Generator
    ) -> int:
        """Place one shipment, drawing its own lognormal lead time.

        Returns the day it is recorded as arriving -- FIFO-adjusted
        already if this lane does not allow crossing. Every unit shipped
        counts against this lane's ``capacity_per_week``, whichever part
        it is or whichever caller placed it -- ``ship`` does not enforce
        the cap itself (see :func:`cap_order_quantity` for that), it only
        records the usage.
        """
        self.capacity_remaining(current_day=order_day)  # apply week rollover bookkeeping
        self._capacity_used_this_week += quantity

        lead_time_days = _draw_lead_time_days(
            median_days=self.lane.lead_time_days_median,
            sigma=self.lane.lead_time_days_sigma,
            rng=rng,
        )
        candidate_arrival_day = order_day + lead_time_days
        return self._record_shipment(
            part_id=part_id, quantity=quantity, candidate_arrival_day=candidate_arrival_day
        )

    def _record_shipment(self, *, part_id: str, quantity: float, candidate_arrival_day: int) -> int:
        """The deterministic half of :meth:`ship`, exercised directly by tests."""
        if self.lane.allow_crossing:
            self._sequence += 1
            heap = self._heap.setdefault(part_id, [])
            heapq.heappush(heap, (candidate_arrival_day, self._sequence, quantity))
            return candidate_arrival_day

        fifo = self._fifo.setdefault(part_id, deque())
        previous_arrival_day = fifo[-1][0] if fifo else None
        arrival_day = _fifo_arrival_day(candidate_arrival_day, previous_arrival_day)
        fifo.append((arrival_day, quantity))
        return arrival_day

    def receive(self, *, part_id: str, current_day: int) -> float:
        """Total quantity of ``part_id`` arriving at or before ``current_day``."""
        arrived = 0.0

        fifo = self._fifo.get(part_id)
        if fifo is not None:
            while fifo and fifo[0][0] <= current_day:
                _, quantity = fifo.popleft()
                arrived += quantity

        heap = self._heap.get(part_id)
        if heap is not None:
            while heap and heap[0][0] <= current_day:
                _, _, quantity = heapq.heappop(heap)
                arrived += quantity

        return arrived

    def outstanding(self, *, part_id: str) -> float:
        """Total quantity of ``part_id`` in transit on this lane right now.

        Non-destructive, unlike :meth:`receive` -- this is a read of both
        queues' total quantity, whatever their arrival days, with nothing
        popped. Session 22's review found this method missing was exactly
        why nothing could read real in-transit inventory without reaching
        into ``_fifo``/``_heap`` directly (as the tests once had to); this
        is the accessor that removes that need.
        """
        fifo_total = sum(quantity for _, quantity in self._fifo.get(part_id, ()))
        heap_total = sum(quantity for _, _, quantity in self._heap.get(part_id, ()))
        return fifo_total + heap_total


@dataclass
class NetworkShipments:
    """One :class:`LaneShipments` per lane, keyed by lane id."""

    lanes: dict[str, LaneShipments]

    @classmethod
    def from_network(cls, network: Network) -> NetworkShipments:
        """One empty :class:`LaneShipments` per lane in ``network``."""
        return cls(lanes={lane.id: LaneShipments(lane=lane) for lane in network.lanes})

    def ship(
        self,
        *,
        lane_id: str,
        part_id: str,
        quantity: float,
        order_day: int,
        rng: np.random.Generator,
    ) -> int:
        """Place one shipment of ``part_id`` on ``lane_id``. See :meth:`LaneShipments.ship`."""
        return self.lanes[lane_id].ship(
            part_id=part_id, quantity=quantity, order_day=order_day, rng=rng
        )

    def receive(self, *, lane_id: str, part_id: str, current_day: int) -> float:
        """Quantity of ``part_id`` arriving on ``lane_id`` by ``current_day``."""
        return self.lanes[lane_id].receive(part_id=part_id, current_day=current_day)

    def capacity_remaining(self, *, lane_id: str, current_day: int) -> float:
        """``lane_id``'s unused weekly capacity. See :meth:`LaneShipments.capacity_remaining`."""
        return self.lanes[lane_id].capacity_remaining(current_day=current_day)

    def outstanding_at_node(self, *, node_id: str, part_id: str) -> float:
        """Real in-transit ``part_id`` inbound to ``node_id``, across every lane.

        Sums :meth:`LaneShipments.outstanding` over every lane whose
        ``destination_id`` is ``node_id`` -- each :class:`LaneShipments`
        already carries its own :class:`daysofcover.models.network.Lane`,
        so no separate node/lane map is needed here. This is what a
        reorder's inventory position (on-hand plus on-order) reads
        instead of a separately maintained counter -- see
        :mod:`daysofcover.engine.state`'s module docstring for why that
        counter is gone.
        """
        return sum(
            lane_shipments.outstanding(part_id=part_id)
            for lane_shipments in self.lanes.values()
            if lane_shipments.lane.destination_id == node_id
        )
