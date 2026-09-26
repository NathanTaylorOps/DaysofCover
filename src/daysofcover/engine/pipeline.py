"""Per-shipment in-transit records, validated against cases 5 and 6.

The build plan's engine methodology names per-shipment records as part of
the core state -- "needed for lane and port closures holding cargo, for
Little's law, and for the LP's starting inventory" -- rather than the
aggregate day-indexed pipeline arrays the Stage 1 spike
(:mod:`daysofcover.engine.single_node`) used to get ADR-008 confirmed
quickly. This module is where that upgrade happens: state literally is a
per-unit record (an order's dispatch day and, once drawn, its arrival
day), not a count.

The two cases this buys validation against both need that: case 5 (Palm's
theorem) needs stochastic, independently drawn per-order lead times with
crossing allowed (an earlier order can arrive after a later one -- true
for lognormal lead times drawn per shipment, false for the spike's
day-indexed array, which could never model that); case 6 (Little's law on
the shipment pipeline) needs each unit's own order day and the day it was
actually sold, which only a per-unit record carries.

Demand here is unit Poisson (matching case 5's reference exactly): each
day, ``lam_per_day`` gives a Poisson count of individual unit demands, and
the policy is one-for-one base-stock -- every unit sold immediately
triggers a replacement order with its own independent lognormal lead time.
This is still a single node, still no BOM or allocation; those come once
this record shape is threaded through the multi-node state the remaining
Stage 1 sessions build.
"""

from __future__ import annotations

import heapq
import math
from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PipelineStats:
    """Pooled statistics from :func:`simulate_unit_base_stock_pipeline`."""

    mean_outstanding_orders: float
    """Case 5's comparator: average number of units currently in transit."""

    mean_pipeline: float
    """In-transit plus on-hand, averaged over the measured days -- the L
    in case 6's Little's law check."""

    mean_sojourn_days: float
    """Average time from a unit's order day to the day it was sold -- the
    W in case 6's Little's law check."""

    arrival_rate_per_day: float
    """Units sold per measured day, pooled across replications -- the
    lambda in case 6's Little's law check (the empirical throughput, not
    the input ``lam_per_day``, though in steady state they agree)."""


def lognormal_mean_days(median_days: float, sigma: float) -> float:
    """E[L] for a lognormal lead time given as (median, sigma).

    The schema (:class:`daysofcover.models.network.LognormalParams`)
    stores a lead time as its median and sigma, not its underlying normal
    mean; median_days = exp(mu), so mu = ln(median_days) and
    E[L] = exp(mu + sigma^2 / 2) = median_days * exp(sigma^2 / 2).
    """
    mu = math.log(median_days)
    return float(math.exp(mu + sigma**2 / 2))


def _simulate_one_replication(
    *,
    lam_per_day: float,
    lead_time_median_days: float,
    lead_time_sigma: float,
    order_up_to: int,
    n_days: int,
    warmup_days: int,
    seed: int,
) -> tuple[list[int], list[int], list[int]]:
    """One replication's raw samples: (outstanding, pipeline, sojourns).

    State is genuinely per-shipment: ``in_transit`` is a min-heap of
    ``(arrival_day, order_day)`` records (crossing allowed -- nothing
    keeps it FIFO), ``on_hand`` and ``backorder`` are FIFO queues of order
    days. A day's arrivals are matched against any waiting backorder
    before joining on-hand, so a unit's sojourn (order day to sale day) is
    read directly off its own record either way.
    """
    rng = np.random.default_rng(seed)
    mu = math.log(lead_time_median_days)

    in_transit: list[tuple[int, int]] = []
    on_hand: deque[int] = deque()
    backorder: deque[int] = deque()

    outstanding_samples: list[int] = []
    pipeline_samples: list[int] = []
    sojourns: list[int] = []

    def place_order(order_day: int) -> None:
        lead_time = rng.lognormal(mean=mu, sigma=lead_time_sigma)
        lead_time_days = max(1, round(lead_time))
        heapq.heappush(in_transit, (order_day + lead_time_days, order_day))

    for _ in range(order_up_to):
        place_order(0)

    for day in range(n_days):
        while in_transit and in_transit[0][0] <= day:
            _, order_day = heapq.heappop(in_transit)
            if backorder:
                waiting_order_day = backorder.popleft()
                if day >= warmup_days:
                    sojourns.append(day - waiting_order_day)
            else:
                on_hand.append(order_day)

        for _ in range(int(rng.poisson(lam_per_day))):
            if on_hand:
                unit_order_day = on_hand.popleft()
                if day >= warmup_days:
                    sojourns.append(day - unit_order_day)
            else:
                backorder.append(day)
            place_order(day)

        if day >= warmup_days:
            outstanding_samples.append(len(in_transit))
            pipeline_samples.append(len(in_transit) + len(on_hand))

    return outstanding_samples, pipeline_samples, sojourns


def simulate_unit_base_stock_pipeline(
    *,
    lam_per_day: float,
    lead_time_median_days: float,
    lead_time_sigma: float,
    order_up_to: int,
    n_reps: int,
    n_days: int,
    warmup_days: int,
    seed: int,
) -> PipelineStats:
    """One-for-one base-stock over per-shipment records, pooled over reps.

    ``order_up_to`` should be generous relative to
    ``lam_per_day * lognormal_mean_days(...)`` (see the validation test for
    the margin used there): a rare stockout is handled correctly
    (backordered, matched FIFO against the next arrival), but this
    function's job is to validate the per-shipment bookkeeping, not
    backorder recovery -- that is a different validation case, covered
    once the multi-node engine's allocation rules exist.
    """
    all_outstanding: list[int] = []
    all_pipeline: list[int] = []
    all_sojourns: list[int] = []
    n_sold = 0

    for rep in range(n_reps):
        outstanding, pipeline, sojourns = _simulate_one_replication(
            lam_per_day=lam_per_day,
            lead_time_median_days=lead_time_median_days,
            lead_time_sigma=lead_time_sigma,
            order_up_to=order_up_to,
            n_days=n_days,
            warmup_days=warmup_days,
            seed=seed + rep,
        )
        all_outstanding.extend(outstanding)
        all_pipeline.extend(pipeline)
        all_sojourns.extend(sojourns)
        n_sold += len(sojourns)

    measured_days = n_reps * (n_days - warmup_days)

    return PipelineStats(
        mean_outstanding_orders=float(np.mean(all_outstanding)),
        mean_pipeline=float(np.mean(all_pipeline)),
        mean_sojourn_days=float(np.mean(all_sojourns)),
        arrival_rate_per_day=n_sold / measured_days,
    )
