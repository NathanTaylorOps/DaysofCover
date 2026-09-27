"""The AND/OR structural screen, tested on the three-node chain the build
plan itself names, plus a redundant-path case to confirm the screen only
flags a removal that actually severs every path.
"""

from __future__ import annotations

from daysofcover.lp.structure import structural_convergence
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


def _seasonal_profile(*, base_weekly_rate: float) -> SeasonalDemandProfile:
    return SeasonalDemandProfile(
        base_weekly_rate=base_weekly_rate, weekly_multipliers=[1.0] * 52, dispersion=1.0
    )


def _chain_network() -> Network:
    """n1 (plant) -> n2 (dc) -> n3 (customer): a single path, no redundancy."""
    n1 = Node(id="n1", name="Plant", type=NodeType.PLANT, region="AU")
    n2 = Node(id="n2", name="DC", type=NodeType.DC, region="AU")
    n3 = Node(id="n3", name="Customer", type=NodeType.CUSTOMER, region="AU")
    lane_12 = Lane(
        id="lane-12",
        origin_id="n1",
        destination_id="n2",
        mode=LaneMode.ROAD,
        lead_time_days_median=1.0,
        lead_time_days_sigma=0.0,
        capacity_per_week=1000.0,
        unit_cost=1.0,
        currency="AUD",
    )
    lane_23 = Lane(
        id="lane-23",
        origin_id="n2",
        destination_id="n3",
        mode=LaneMode.ROAD,
        lead_time_days_median=1.0,
        lead_time_days_sigma=0.0,
        capacity_per_week=1000.0,
        unit_cost=1.0,
        currency="AUD",
    )
    part_a = Part(
        id="part-a",
        name="Part A",
        suppliers=[SupplySource(node_id="n1", split_ratio=1.0)],
        unit_cost=1.0,
        currency="AUD",
    )
    sku_a = SKU(
        id="sku-a",
        name="SKU A",
        price={"AUD": 100.0},
        margin_fraction=0.5,
        currency="AUD",
        bom=[BOMLine(part_id="part-a", quantity=1.0)],
        production_lead_time_days=3.0,
        batch_size=1.0,
    )
    customer = Customer(
        id="n3",
        name="Customer",
        demand={"sku-a": _seasonal_profile(base_weekly_rate=70.0)},
        backlog_window_days=30,
        allocation_priority=0,
    )
    return Network(
        base_currency="AUD",
        nodes=[n1, n2, n3],
        lanes=[lane_12, lane_23],
        parts=[part_a],
        skus=[sku_a],
        customers=[customer],
    )


def test_removing_the_only_dc_cuts_the_full_value_chain() -> None:
    network = _chain_network()

    result = structural_convergence(network, removed_element_id="n2")

    assert result.cut_pairs == (("n3", "sku-a"),)
    assert result.convergence_fraction == 1.0


def test_removing_the_only_plant_cuts_the_full_value_chain() -> None:
    network = _chain_network()

    result = structural_convergence(network, removed_element_id="n1")

    assert result.cut_pairs == (("n3", "sku-a"),)
    assert result.convergence_fraction == 1.0


def _chain_with_redundant_dc_network() -> Network:
    """n1 (plant) -> {n2, n2b} (two independent DCs) -> n3 (customer)."""
    network = _chain_network()
    n2b = Node(id="n2b", name="DC backup", type=NodeType.DC, region="AU")
    lane_1_2b = Lane(
        id="lane-1-2b",
        origin_id="n1",
        destination_id="n2b",
        mode=LaneMode.ROAD,
        lead_time_days_median=1.0,
        lead_time_days_sigma=0.0,
        capacity_per_week=1000.0,
        unit_cost=1.0,
        currency="AUD",
    )
    lane_2b_3 = Lane(
        id="lane-2b-3",
        origin_id="n2b",
        destination_id="n3",
        mode=LaneMode.ROAD,
        lead_time_days_median=1.0,
        lead_time_days_sigma=0.0,
        capacity_per_week=1000.0,
        unit_cost=1.0,
        currency="AUD",
    )
    return network.model_copy(
        update={
            "nodes": [*network.nodes, n2b],
            "lanes": [*network.lanes, lane_1_2b, lane_2b_3],
        }
    )


def test_removing_one_of_two_redundant_dcs_cuts_nothing() -> None:
    network = _chain_with_redundant_dc_network()

    result = structural_convergence(network, removed_element_id="n2")

    assert result.cut_pairs == ()
    assert result.convergence_fraction == 0.0


def test_removing_the_shared_plant_still_cuts_everything_despite_redundant_dcs() -> None:
    network = _chain_with_redundant_dc_network()

    result = structural_convergence(network, removed_element_id="n1")

    assert result.cut_pairs == (("n3", "sku-a"),)
    assert result.convergence_fraction == 1.0
