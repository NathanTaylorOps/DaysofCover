"""Property tests: invariants that must hold for any valid input, not
just the unit tests' hand-picked examples.

Session 22, the third of the five remaining Engine-milestone items. Each
property below is checked against the exact functions the unit tests
already exercise with fixed examples -- these do not duplicate that
coverage, they widen the input space Hypothesis is allowed to search for
a counterexample, on an invariant the function's own docstring already
promises: an allocation never exceeds what was requested or what was
available; a capped order is always zero or at least the MOQ and never
over capacity; a supplier split always accounts for the whole order; the
state chassis is always sized exactly from the network it was built
from.

Uses the strategies in ``tests/strategies.py`` (not duplicated here) for
anything that needs a *valid* network, part-supplier list, or id set --
see that module's docstring for why a hand-rolled ``st.builds`` would not
do.
"""

from __future__ import annotations

import hypothesis.strategies as st
from hypothesis import given, settings

from daysofcover.engine.allocation import (
    CustomerOrder,
    allocate_batch_aware_components,
    allocate_by_backlog_proportion,
    allocate_by_margin_priority,
    allocate_finished_goods_to_orders,
    supplier_split_ratios,
)
from daysofcover.engine.shipments import cap_order_quantity
from daysofcover.engine.state import NetworkState
from daysofcover.models.network import Network, SupplySource
from strategies import networks, supplier_scenarios

_TOLERANCE = 1e-6
_SKU_IDS = ["sku-a", "sku-b", "sku-c"]


def _nonneg_quantities(sku_ids: list[str]) -> st.SearchStrategy[dict[str, float]]:
    return st.fixed_dictionaries(
        {
            sku_id: st.floats(
                min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False
            )
            for sku_id in sku_ids
        }
    )


@given(
    available_quantity=st.floats(
        min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False
    ),
    requested_by_sku=_nonneg_quantities(_SKU_IDS),
    backlog_by_sku=_nonneg_quantities(_SKU_IDS),
)
def test_backlog_proportion_never_exceeds_request_or_availability(
    available_quantity: float,
    requested_by_sku: dict[str, float],
    backlog_by_sku: dict[str, float],
) -> None:
    allocation = allocate_by_backlog_proportion(
        available_quantity=available_quantity,
        requested_by_sku=requested_by_sku,
        backlog_by_sku=backlog_by_sku,
    )

    for sku, quantity in allocation.items():
        assert quantity >= 0.0
        assert quantity <= requested_by_sku[sku] + _TOLERANCE
    assert sum(allocation.values()) <= available_quantity + _TOLERANCE


@given(
    available_quantity=st.floats(
        min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False
    ),
    requested_by_sku=_nonneg_quantities(_SKU_IDS),
    margin_by_sku=_nonneg_quantities(_SKU_IDS),
)
def test_margin_priority_never_exceeds_request_or_availability(
    available_quantity: float,
    requested_by_sku: dict[str, float],
    margin_by_sku: dict[str, float],
) -> None:
    allocation = allocate_by_margin_priority(
        available_quantity=available_quantity,
        requested_by_sku=requested_by_sku,
        margin_by_sku=margin_by_sku,
    )

    for sku, quantity in allocation.items():
        assert quantity >= 0.0
        assert quantity <= requested_by_sku[sku] + _TOLERANCE
    assert sum(allocation.values()) <= available_quantity + _TOLERANCE


@given(
    available_quantity=st.floats(
        min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False
    ),
    orders=st.lists(
        st.builds(
            CustomerOrder,
            customer_id=st.sampled_from(["cust-a", "cust-b", "cust-c"]),
            order_day=st.integers(min_value=0, max_value=100),
            quantity=st.floats(
                min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False
            ),
            priority=st.integers(min_value=0, max_value=3),
        ),
        max_size=6,
    ),
)
def test_finished_goods_allocation_never_exceeds_order_or_availability(
    available_quantity: float, orders: list[CustomerOrder]
) -> None:
    fulfilled = allocate_finished_goods_to_orders(
        available_quantity=available_quantity, orders=orders
    )

    assert len(fulfilled) == len(orders)
    for order, quantity in zip(orders, fulfilled, strict=True):
        assert quantity >= 0.0
        assert quantity <= order.quantity + _TOLERANCE
    assert sum(fulfilled) <= available_quantity + _TOLERANCE


@given(
    desired_quantity=st.floats(
        min_value=-100.0, max_value=1000.0, allow_nan=False, allow_infinity=False
    ),
    moq=st.none()
    | st.floats(min_value=0.0, max_value=200.0, allow_nan=False, allow_infinity=False),
    capacity_remaining=st.floats(
        min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False
    ),
)
def test_capped_order_is_never_over_capacity_and_never_a_sub_moq_partial(
    desired_quantity: float, moq: float | None, capacity_remaining: float
) -> None:
    capped = cap_order_quantity(
        desired_quantity=desired_quantity, moq=moq, capacity_remaining=capacity_remaining
    )

    assert capped >= 0.0
    assert capped <= capacity_remaining + _TOLERANCE
    assert capped == 0.0 or moq is None or capped >= moq - _TOLERANCE


@given(
    scenario=supplier_scenarios(),
    primary_down_since_day=st.none() | st.integers(min_value=0, max_value=50),
    current_day=st.integers(min_value=0, max_value=100),
)
@settings(deadline=None)
def test_supplier_split_ratios_always_account_for_the_whole_order(
    scenario: tuple[list[str], list[SupplySource]],
    primary_down_since_day: int | None,
    current_day: int,
) -> None:
    _node_ids, suppliers = scenario

    ratios = supplier_split_ratios(
        suppliers=suppliers,
        primary_down_since_day=primary_down_since_day,
        current_day=current_day,
    )

    assert abs(sum(ratios.values()) - 1.0) < _TOLERANCE
    for ratio in ratios.values():
        assert ratio >= 0.0


@given(network=networks())
@settings(deadline=None)
def test_state_chassis_is_sized_from_the_network_it_was_built_from(network: Network) -> None:
    state = NetworkState.from_network(network)

    n_nodes = len(network.nodes)
    n_parts = len(network.parts)
    n_skus = len(network.skus)

    assert state.on_hand.shape == (n_nodes, n_parts)
    assert state.backlog.shape == (n_nodes, n_parts)
    assert state.finished_on_hand.shape == (n_nodes, n_skus)
    assert state.finished_backlog.shape == (n_nodes, n_skus)

    for node in network.nodes:
        assert 0 <= state.node_index(node.id) < n_nodes
    for part in network.parts:
        assert 0 <= state.part_index(part.id) < n_parts


@given(
    available_batches=st.integers(min_value=0, max_value=100),
    batch_sizes=st.lists(
        st.integers(min_value=1, max_value=12), min_size=3, max_size=3
    ),
    requests=st.lists(
        st.integers(min_value=0, max_value=20), min_size=3, max_size=3
    ),
    backlogs=st.lists(
        st.integers(min_value=0, max_value=100), min_size=3, max_size=3
    ),
    margins=st.lists(
        st.integers(min_value=0, max_value=100), min_size=3, max_size=3
    ),
    rule=st.sampled_from(["backlog_proportion", "margin_priority"]),
)
@settings(deadline=None)
def test_batch_allocation_conserves_stock_and_is_order_independent(
    available_batches: int,
    batch_sizes: list[int],
    requests: list[int],
    backlogs: list[int],
    margins: list[int],
    rule: str,
) -> None:
    """All allocated stock fits whole batches and is stable under SKU permutation."""
    batch_by_sku = dict(zip(_SKU_IDS, batch_sizes, strict=True))
    requested_by_sku = {
        sku: batch_by_sku[sku] * count
        for sku, count in zip(_SKU_IDS, requests, strict=True)
    }
    backlog_by_sku = dict(zip(_SKU_IDS, backlogs, strict=True))
    margin_by_sku = dict(zip(_SKU_IDS, margins, strict=True))
    available = float(available_batches)

    def allocate(ids: list[str]) -> dict[str, float]:
        return allocate_batch_aware_components(
            available_quantity=available,
            requested_by_sku={sku: float(requested_by_sku[sku]) for sku in ids},
            batch_component_by_sku={sku: float(batch_by_sku[sku]) for sku in ids},
            backlog_by_sku={sku: float(backlog_by_sku[sku]) for sku in ids},
            margin_by_sku={sku: float(margin_by_sku[sku]) for sku in ids},
            rule=rule,
        )

    result = allocate(_SKU_IDS)
    assert result == allocate(list(reversed(_SKU_IDS)))
    assert sum(result.values()) <= available + _TOLERANCE
    for sku, quantity in result.items():
        assert quantity >= 0
        assert quantity <= requested_by_sku[sku] + _TOLERANCE
        assert quantity % batch_by_sku[sku] == 0


@given(
    stock_tenths=st.integers(min_value=0, max_value=10000),
    batch_tenths=st.integers(min_value=1, max_value=50),
    requested_batches=st.integers(min_value=0, max_value=100),
    rule=st.sampled_from(["backlog_proportion", "margin_priority"]),
)
@settings(deadline=None)
def test_fractional_batch_allocation_never_overconsumes(
    stock_tenths: int,
    batch_tenths: int,
    requested_batches: int,
    rule: str,
) -> None:
    """Fractional production batches must never consume more physical stock."""
    batch = batch_tenths / 10.0
    available = stock_tenths / 10.0
    requested = batch * requested_batches
    allocation = allocate_batch_aware_components(
        available_quantity=available,
        requested_by_sku={"sku-a": requested, "sku-b": requested},
        batch_component_by_sku={"sku-a": batch, "sku-b": batch},
        backlog_by_sku={"sku-a": 1.0, "sku-b": 1.0},
        margin_by_sku={"sku-a": 1.0, "sku-b": 1.0},
        rule=rule,
    )
    assert sum(allocation.values()) <= available + _TOLERANCE
    for quantity in allocation.values():
        assert quantity >= 0
        assert quantity <= requested + _TOLERANCE
        assert abs(quantity / batch - round(quantity / batch)) < _TOLERANCE
