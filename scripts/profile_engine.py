"""Profiling pass: per-day wall-clock time of the daily-step engine on a
network sized to the build plan's target of "about 40 nodes, 25 parts",
against its 200 ms/day target.

Honest scoping note, since this script's numbers are read alongside
that target: :func:`daysofcover.engine.daily_step.advance_one_day` is a
*single plant's* daily step (session 14's docstring is explicit that a
full multi-node driver -- looping the day forward across every plant,
distributor and lane in a network -- is still ahead). Node count beyond
that one plant does not change this call's own cost; a bigger network
mostly means a bigger, mostly-idle :class:`~daysofcover.engine.state.
NetworkState`. What this script actually measures -- and what genuinely
does scale with the plan's numbers -- is the cost of one plant handling
``n_skus`` SKUs that each carry a ``n_parts``-line BOM, one part shared
and reordered across every SKU, which is the real per-day cost the
build plan's "200 ms" was written against for the one plant a v0.1
network needs to get right first. A full network-wide loop, once it
exists, is a sum of calls shaped like this one, so this is the number
that predicts it.

Run as ``python scripts/profile_engine.py`` (or ``uv run python
scripts/profile_engine.py``); prints mean, p95 and max per-day duration
against the target and exits non-zero if the mean misses it, so it can
also be wired into CI later if the plan wants that.
"""

from __future__ import annotations

import sys
import time

import numpy as np

from daysofcover.data.synthetic import PLANT_ID, generate_synthetic_network
from daysofcover.engine.daily_step import SkuProductionSpec, advance_one_day
from daysofcover.engine.production import ProductionQueue
from daysofcover.engine.shipments import NetworkShipments
from daysofcover.engine.state import NetworkState

N_NODES = 40
N_PARTS = 25
N_SKUS = 5
N_CUSTOMERS = 5
N_DAYS = 365
TARGET_MS = 200.0
SEED = 20260926


def run(*, n_nodes: int, n_parts: int, n_skus: int, n_days: int) -> list[float]:
    """Per-day wall-clock durations (seconds) advancing one plant ``n_days`` times."""
    network = generate_synthetic_network(
        n_nodes=n_nodes, n_parts=n_parts, n_skus=n_skus, n_customers=N_CUSTOMERS, seed=SEED
    )
    state = NetworkState.from_network(network)
    shipments = NetworkShipments.from_network(network)
    rng = np.random.default_rng(SEED)

    scarce_part_id = network.parts[0].id
    inbound_lane_id = "lane-supplier-0"
    sku_specs = [
        SkuProductionSpec(
            finished_sku_id=sku.id,
            bom=sku.bom,
            capacity_per_week=1_000.0,
            batch_size=sku.batch_size,
            production_lead_time_days=sku.production_lead_time_days,
            orders=[],
            production_queue=ProductionQueue(),
            margin_fraction=sku.margin_fraction,
        )
        for sku in network.skus
    ]

    durations: list[float] = []
    for day in range(n_days):
        start = time.perf_counter()
        advance_one_day(
            state=state,
            shipments=shipments,
            plant_node_id=PLANT_ID,
            component_part_id=scarce_part_id,
            inbound_lane_id=inbound_lane_id,
            sku_specs=sku_specs,
            current_day=day,
            order_up_to=5_000.0,
            review_period_days=7,
            rng=rng,
        )
        durations.append(time.perf_counter() - start)

    return durations


def main() -> int:
    durations = run(n_nodes=N_NODES, n_parts=N_PARTS, n_skus=N_SKUS, n_days=N_DAYS)

    mean_ms = 1000.0 * sum(durations) / len(durations)
    sorted_ms = sorted(1000.0 * d for d in durations)
    p95_ms = sorted_ms[int(0.95 * len(sorted_ms))]
    max_ms = sorted_ms[-1]
    met = mean_ms <= TARGET_MS

    print(f"{N_NODES} nodes, {N_PARTS} parts, {N_SKUS} SKUs, {N_DAYS} simulated days")
    print(f"mean:   {mean_ms:.4f} ms/day")
    print(f"p95:    {p95_ms:.4f} ms/day")
    print(f"max:    {max_ms:.4f} ms/day")
    print(f"target: {TARGET_MS:.0f} ms/day -- {'MET' if met else 'NOT MET'}")

    return 0 if met else 1


if __name__ == "__main__":
    sys.exit(main())
