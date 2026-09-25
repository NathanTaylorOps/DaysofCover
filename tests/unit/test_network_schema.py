"""Schema v0 rejects the malformed inputs the security section names:
a lane to a missing node, a BOM referencing a missing part, an unknown
field, and an oversized network.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from daysofcover.models import (
    SKU,
    BOMLine,
    Lane,
    LaneMode,
    Network,
    Node,
    NodeType,
)


def _plant() -> Node:
    return Node(id="plant", name="Plant", type=NodeType.PLANT, region="AU")


def _supplier() -> Node:
    return Node(id="supplier", name="Supplier", type=NodeType.SUPPLIER, region="CN")


def _lane(origin: str = "supplier", destination: str = "plant") -> Lane:
    return Lane(
        id="lane1",
        origin_id=origin,
        destination_id=destination,
        mode=LaneMode.OCEAN,
        lead_time_days_median=20,
        lead_time_days_sigma=0.2,
        capacity_per_week=100,
        unit_cost=1.0,
        currency="USD",
    )


def test_valid_minimal_network_is_accepted() -> None:
    network = Network(
        base_currency="AUD",
        nodes=[_supplier(), _plant()],
        lanes=[_lane()],
        parts=[],
    )
    assert len(network.nodes) == 2


def test_lane_to_a_missing_node_is_rejected() -> None:
    with pytest.raises(ValidationError, match="not a known node id"):
        Network(
            base_currency="AUD",
            nodes=[_supplier(), _plant()],
            lanes=[_lane(destination="warehouse_that_does_not_exist")],
            parts=[],
        )


def test_bom_referencing_a_missing_part_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown part_id"):
        Network(
            base_currency="AUD",
            nodes=[_supplier(), _plant()],
            lanes=[_lane()],
            parts=[],
            skus=[
                SKU(
                    id="sku1",
                    name="Widget",
                    price={"AUD": 100.0},
                    margin_fraction=0.4,
                    currency="AUD",
                    bom=[BOMLine(part_id="part_that_does_not_exist", quantity=1)],
                    production_lead_time_days=7,
                    batch_size=10,
                )
            ],
        )


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Node.model_validate(
            {
                "id": "n1",
                "name": "Node",
                "type": "supplier",
                "region": "AU",
                "this_field_does_not_exist": True,
            }
        )


def test_oversized_network_is_rejected() -> None:
    too_many_nodes = [
        Node(id=f"n{i}", name=f"Node {i}", type=NodeType.SUPPLIER, region="AU") for i in range(101)
    ]
    with pytest.raises(ValidationError):
        Network(base_currency="AUD", nodes=too_many_nodes, lanes=[], parts=[])


def test_three_point_estimate_must_be_ordered() -> None:
    from daysofcover.models import ThreePointDays

    with pytest.raises(ValidationError, match="min <= likely <= max"):
        ThreePointDays(min_days=10, likely_days=5, max_days=20)


def test_supplier_split_ratios_must_sum_to_one() -> None:
    from daysofcover.models import Part, SupplySource

    with pytest.raises(ValidationError, match="must sum to"):
        Part(
            id="part1",
            name="Widget part",
            suppliers=[
                SupplySource(node_id="supplier", split_ratio=0.5),
                SupplySource(node_id="supplier2", split_ratio=0.3),
            ],
            unit_cost=1.0,
            currency="USD",
        )
