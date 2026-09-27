"""The weekly time-indexed cover variant (:mod:`daysofcover.lp.weekly`).

Two things to check that the flat aggregate model's own tests don't touch
at all: (1) with no seasonality (``weekly_multipliers`` all ``1.0``), the
weekly bisection's answer, converted to days, should agree with the flat
model's own continuous ``solve_cover`` on the identical network -- both
are answering the same physical question, just at different granularity;
(2) with real seasonality, the worst start week actually matters -- the
same starting stock survives longer starting in a low-demand week than
starting right before a demand spike, and ``solve_weekly_cover`` has to
find that worst case itself rather than just checking week 0.

A hand-derivation caught a real sign bug in ``_build_weekly``'s per-week
balance equation while writing these tests (the RHS had the wrong sign,
so ending inventory rose with demand and fell with starting stock --
backwards): fixed before any of the assertions below were written, not
adjusted to match a wrong answer.
"""

from __future__ import annotations

from daysofcover.lp.aggregate import sku_key, solve_cover
from daysofcover.lp.weekly import solve_weekly_cover
from daysofcover.models.network import (
    SKU,
    BOMLine,
    Customer,
    Network,
    Node,
    NodeType,
    Part,
    SeasonalDemandProfile,
    SupplySource,
)


def _flat_profile(*, base_weekly_rate: float) -> SeasonalDemandProfile:
    return SeasonalDemandProfile(
        base_weekly_rate=base_weekly_rate, weekly_multipliers=[1.0] * 52, dispersion=1.0
    )


def _single_customer_network(*, demand_profile: SeasonalDemandProfile) -> Network:
    """One customer, no plant, no lanes -- the same no-production shape used elsewhere."""
    supplier = Node(id="supplier-1", name="Supplier", type=NodeType.SUPPLIER, region="AU")
    customer_node = Node(id="cust-1", name="Customer", type=NodeType.CUSTOMER, region="AU")
    part_a = Part(
        id="part-a",
        name="Part A",
        suppliers=[SupplySource(node_id="supplier-1", split_ratio=1.0)],
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
        id="cust-1",
        name="Customer",
        demand={"sku-a": demand_profile},
        backlog_window_days=30,
        allocation_priority=0,
    )
    return Network(
        base_currency="AUD",
        nodes=[supplier, customer_node],
        lanes=[],
        parts=[part_a],
        skus=[sku_a],
        customers=[customer],
    )


def test_no_seasonality_matches_the_flat_models_own_continuous_cover_days() -> None:
    # 210 units at a flat 70/week (10/day) is exactly 3 weeks -- both
    # models should land on that, the flat one in days, the weekly one
    # in whole weeks.
    network = _single_customer_network(demand_profile=_flat_profile(base_weekly_rate=70.0))
    starting_inventory = {("cust-1", sku_key("sku-a")): 210.0}

    flat_result = solve_cover(
        network, removed_element_id=None, starting_inventory=starting_inventory
    )
    assert flat_result.status == "optimal"
    assert flat_result.cover_days == 21.0

    weekly_result = solve_weekly_cover(
        network,
        removed_element_id=None,
        starting_inventory=starting_inventory,
        start_weeks=range(1),  # no seasonality -- every start week is identical
    )
    assert weekly_result.cover_weeks == 3
    assert weekly_result.cover_weeks * 7 == flat_result.cover_days
    assert not weekly_result.at_cap


def test_zero_weeks_when_even_the_first_weeks_demand_cannot_be_met() -> None:
    # 50 units against 70/week: a genuine shortfall inside week 0 itself.
    network = _single_customer_network(demand_profile=_flat_profile(base_weekly_rate=70.0))
    starting_inventory = {("cust-1", sku_key("sku-a")): 50.0}

    result = solve_weekly_cover(
        network,
        removed_element_id=None,
        starting_inventory=starting_inventory,
        start_weeks=range(1),
    )

    assert result.cover_weeks == 0


def test_worst_start_week_is_the_one_right_before_the_demand_spike() -> None:
    # Two low weeks (10/week) followed by fifty high weeks (40/week).
    # 21 units survives two low weeks starting at week 0 (10 then 10,
    # 1 left over) but not a single high week (40) starting at week 2.
    multipliers = [0.5, 0.5] + [2.0] * 50
    profile = SeasonalDemandProfile(
        base_weekly_rate=20.0, weekly_multipliers=multipliers, dispersion=1.0
    )
    network = _single_customer_network(demand_profile=profile)
    starting_inventory = {("cust-1", sku_key("sku-a")): 21.0}

    result = solve_weekly_cover(
        network,
        removed_element_id=None,
        starting_inventory=starting_inventory,
        start_weeks=range(4),
    )

    assert result.cover_weeks == 0
    assert result.worst_start_week == 2


def test_starting_in_the_low_season_survives_longer_than_the_spike() -> None:
    # Same seasonal pattern, but with enough stock (21 units) that
    # starting in the low season (week 0) covers 2 full weeks, strictly
    # more than the 0 weeks available starting right at the spike.
    multipliers = [0.5, 0.5] + [2.0] * 50
    profile = SeasonalDemandProfile(
        base_weekly_rate=20.0, weekly_multipliers=multipliers, dispersion=1.0
    )
    network = _single_customer_network(demand_profile=profile)
    starting_inventory = {("cust-1", sku_key("sku-a")): 21.0}

    from daysofcover.lp.aggregate import _resolve
    from daysofcover.lp.weekly import _max_feasible_weeks, _weekly_demand_rates

    resolved = _resolve(network, removed_element_id=None)
    rates = _weekly_demand_rates(network, live_node_ids=frozenset(resolved.node_ids))

    low_season_weeks = _max_feasible_weeks(
        resolved, rates, starting_inventory=starting_inventory, start_week=0
    )
    spike_weeks = _max_feasible_weeks(
        resolved, rates, starting_inventory=starting_inventory, start_week=2
    )

    assert low_season_weeks == 2
    assert spike_weeks == 0
    assert low_season_weeks > spike_weeks


def test_surviving_the_full_search_cap_is_reported_rather_than_claimed_infinite() -> None:
    # Ample stock relative to demand should hit MAX_WEEKS_SEARCHED and
    # be flagged at_cap, not misreported as some specific larger number.
    network = _single_customer_network(demand_profile=_flat_profile(base_weekly_rate=1.0))
    starting_inventory = {("cust-1", sku_key("sku-a")): 100_000.0}

    result = solve_weekly_cover(
        network,
        removed_element_id=None,
        starting_inventory=starting_inventory,
        start_weeks=range(1),
    )

    assert result.at_cap
    assert result.cover_weeks == 32
