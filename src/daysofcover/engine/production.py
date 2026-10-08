"""BOM-constrained production planning and completion tracking.

Production feasibility is limited by the plant's daily capacity,
available bill-of-materials components and batch-size requirements.
Component consumption is applied separately from the feasibility
calculation. A production queue tracks the fixed lead time between
starting a batch and receiving finished goods.

Allocation of shared components across SKUs and allocation of finished
goods across customers are handled by separate policy modules.
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
