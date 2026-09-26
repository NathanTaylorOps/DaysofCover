"""Per-shipment in-transit records, generalised across every lane and part.

Session 7's :mod:`daysofcover.engine.pipeline` proved the per-unit record
shape (an order's dispatch day and, once drawn, its arrival day) on a
single implicit lane. This module is where that shape gets threaded
through every real lane in a network, and where the build plan's rule
that session's single pipeline never had to choose between gets
implemented literally: "Shipments on a lane are FIFO (no crossing) unless
allow_crossing; lognormal lead times are drawn per order."

Each lane's shipments queue independently per part: a FIFO lane (the
default, ``allow_crossing=False``) still draws an independent lognormal
lead time for every shipment, but the *arrival order* is constrained --
a shipment can never be recorded as arriving before the one placed ahead
of it on the same lane and part, even when its own draw would have put it
there sooner. ``allow_crossing`` lifts that constraint: shipments arrive
whenever their own draw says to, independent of placement order, which is
exactly session 7's min-heap design generalised from one pipeline to one
per (lane, part).

BOM-driven production, the allocation and split rules, and the
replication runner all still lie ahead; this module only carries goods
in motion on a single lane from a placed order to an arrival day.
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

    def ship(
        self, *, part_id: str, quantity: float, order_day: int, rng: np.random.Generator
    ) -> int:
        """Place one shipment, drawing its own lognormal lead time.

        Returns the day it is recorded as arriving -- FIFO-adjusted
        already if this lane does not allow crossing.
        """
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
