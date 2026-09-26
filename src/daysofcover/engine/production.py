"""BOM-driven production at a plant, capped by capacity and the scarcest part.

The build plan states this in one sentence: "Production at the plant
consumes components per BOM, is capped by plant capacity and by the
scarcest component, and has a one-week lead and a batch size." This
module is that sentence, split into its three independently testable
pieces:

- :func:`feasible_production_units` -- how many units of one SKU could
  start production today, before anything is actually consumed. Three
  caps apply, and the smallest wins: the plant's own daily capacity, the
  scarcest BOM component on hand, and rounding down to a whole number of
  batches.
- :func:`consume_components` -- what production of that many units
  actually costs, in components taken off the shelf.
- :class:`ProductionQueue` -- the lead time between starting a batch and
  it becoming finished goods. Unlike a lane's shipments
  (:mod:`daysofcover.engine.shipments`), a SKU's production lead time
  (:attr:`daysofcover.models.network.SKU.production_lead_time_days`) is a
  fixed schema field, not a distribution drawn per batch, so a
  later-started batch can never finish before an earlier one -- there is
  nothing for FIFO to enforce here, only a plain queue.

Allocation across SKUs when a shared component is scarce, and across
customers when finished goods are scarce, are their own rules the build
plan states separately and are not this module's job; here, one SKU's
production is checked and started in isolation, against whatever
component quantities the caller has already decided to make available to
it.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from daysofcover.models.network import BOMLine


def feasible_production_units(
    *,
    capacity_per_week: float,
    on_hand_by_part: dict[str, float],
    bom: list[BOMLine],
    batch_size: float,
) -> float:
    """The most units of one SKU that could start production today.

    ``on_hand_by_part`` is read, never written -- this only answers how
    many units are feasible, it does not consume anything (see
    :func:`consume_components` for that). A part the BOM needs but that
    is missing from ``on_hand_by_part`` is treated as zero on hand,
    which caps production at zero regardless of the other two limits.
    """
    daily_capacity = capacity_per_week / 7.0
    feasible = daily_capacity

    for line in bom:
        available = on_hand_by_part.get(line.part_id, 0.0)
        units_from_this_part = available / line.quantity
        feasible = min(feasible, units_from_this_part)

    whole_batches = math.floor(feasible / batch_size)
    return max(0.0, whole_batches * batch_size)


def consume_components(
    *, on_hand_by_part: dict[str, float], bom: list[BOMLine], units_produced: float
) -> dict[str, float]:
    """Component on-hand quantities after producing ``units_produced`` units.

    Returns a new dict rather than mutating ``on_hand_by_part`` in
    place, so a caller can compare before and after -- or discard an
    attempt entirely -- without having already committed to it. This
    trusts the caller to have capped ``units_produced`` with
    :func:`feasible_production_units` first; it does not itself refuse a
    quantity that would drive a component negative.
    """
    updated = dict(on_hand_by_part)
    for line in bom:
        updated[line.part_id] = updated.get(line.part_id, 0.0) - units_produced * line.quantity
    return updated


@dataclass
class ProductionQueue:
    """Batches of one SKU in production, each ready after a fixed lead time.

    A plain FIFO deque, not the FIFO-enforcing kind
    :mod:`daysofcover.engine.shipments` needs: because every batch waits
    the same fixed ``lead_time_days`` (rounded to the nearest whole day),
    ready days are already non-decreasing in start order, so there is
    nothing to enforce.
    """

    _queue: deque[tuple[int, float]] = field(default_factory=deque)

    def start(self, *, quantity: float, start_day: int, lead_time_days: float) -> int:
        """Start one batch of ``quantity`` units; returns the day it is ready."""
        ready_day = start_day + round(lead_time_days)
        self._queue.append((ready_day, quantity))
        return ready_day

    def complete(self, *, current_day: int) -> float:
        """Total quantity of batches ready at or before ``current_day``."""
        completed = 0.0
        while self._queue and self._queue[0][0] <= current_day:
            _, quantity = self._queue.popleft()
            completed += quantity
        return completed

    def outstanding(self) -> float:
        """Quantity currently in production, not yet ready."""
        return sum(quantity for _, quantity in self._queue)
