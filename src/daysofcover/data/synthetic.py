"""Generate reproducible synthetic networks for performance profiling.

The configurable network contains a plant, one supplier per part and
additional distribution-tier nodes as needed to meet the requested size.
The topology is deliberately simple and is not intended as a realistic
business case. The generator supports repeatable workload sizing for
engine profiling rather than business interpretation or validation.
"""

from __future__ import annotations

import numpy as np

from daysofcover.models.network import (
    SKU,
    BOMLine,
    Customer,
    Lane,
    LaneMode,
    Network,
    Node,
    NodeType,
    Part,
    SeasonalDemandProfile,
    SupplySource,
)

PLANT_ID = "plant-0"


def generate_synthetic_network(
    *,
    n_nodes: int = 40,
    n_parts: int = 25,
    n_skus: int = 5,
    n_customers: int = 5,
    seed: int = 20260926,
) -> Network:
    """A seeded, schema-valid network with exactly ``n_parts`` parts and
    ``n_nodes`` nodes in total (one plant, one single-sourced supplier
    per part, and the rest as unreferenced distribution-tier padding).

    Every SKU's BOM touches every part (in a small, deterministic
    per-SKU ratio), so with more than one SKU the shared-component
    allocation rules have something real to arbitrate, and every
    customer places demand against every SKU. Raises ``ValueError`` if
    ``n_nodes`` is too small to fit the plant and one supplier per part.
    """
    if n_nodes < n_parts + 1:
        raise ValueError(
            f"n_nodes ({n_nodes}) must be at least n_parts + 1 ({n_parts + 1}) "
            "to fit the plant and one supplier per part"
        )

    rng = np.random.default_rng(seed)

    plant = Node(
        id=PLANT_ID, name="Plant", type=NodeType.PLANT, region="AU", capacity_per_week=100_000.0
    )
    supplier_nodes = [
        Node(id=f"supplier-{i}", name=f"Supplier {i}", type=NodeType.SUPPLIER, region="CN")
        for i in range(n_parts)
    ]
    n_distribution = n_nodes - 1 - n_parts
    distribution_nodes = [
        Node(id=f"dc-{i}", name=f"DC {i}", type=NodeType.DC, region="AU")
        for i in range(n_distribution)
    ]
    nodes = [plant, *supplier_nodes, *distribution_nodes]

    parts = [
        Part(
            id=f"part-{i}",
            name=f"Part {i}",
            suppliers=[SupplySource(node_id=f"supplier-{i}", split_ratio=1.0, is_primary=True)],
            unit_cost=float(rng.uniform(1.0, 50.0)),
            currency="AUD",
        )
        for i in range(n_parts)
    ]

    lanes = [
        Lane(
            id=f"lane-supplier-{i}",
            origin_id=f"supplier-{i}",
            destination_id=PLANT_ID,
            mode=LaneMode.OCEAN,
            lead_time_days_median=float(rng.uniform(5.0, 30.0)),
            lead_time_days_sigma=0.2,
            capacity_per_week=float(rng.uniform(500.0, 2000.0)),
            unit_cost=1.0,
            currency="AUD",
        )
        for i in range(n_parts)
    ]
    lanes.extend(
        Lane(
            id=f"lane-dc-{i}",
            origin_id=PLANT_ID,
            destination_id=f"dc-{i}",
            mode=LaneMode.ROAD,
            lead_time_days_median=float(rng.uniform(1.0, 5.0)),
            lead_time_days_sigma=0.1,
            capacity_per_week=float(rng.uniform(500.0, 2000.0)),
            unit_cost=0.5,
            currency="AUD",
        )
        for i in range(n_distribution)
    )

    skus = [
        SKU(
            id=f"sku-{i}",
            name=f"SKU {i}",
            price={"AUD": 100.0 + 10.0 * i},
            margin_fraction=float(0.1 + 0.05 * (i % 5)),
            currency="AUD",
            bom=[
                BOMLine(part_id=f"part-{p}", quantity=float(1 + (p + i) % 3))
                for p in range(n_parts)
            ],
            production_lead_time_days=3.0,
            batch_size=10.0,
        )
        for i in range(n_skus)
    ]

    customers = [
        Customer(
            id=f"customer-{c}",
            name=f"Customer {c}",
            demand={
                f"sku-{i}": SeasonalDemandProfile(
                    base_weekly_rate=float(rng.uniform(20.0, 100.0)),
                    weekly_multipliers=[1.0] * 52,
                    dispersion=10.0,
                )
                for i in range(n_skus)
            },
            backlog_window_days=14,
            allocation_priority=c,
        )
        for c in range(n_customers)
    ]

    return Network(
        base_currency="AUD",
        nodes=nodes,
        lanes=lanes,
        parts=parts,
        skus=skus,
        customers=customers,
    )
