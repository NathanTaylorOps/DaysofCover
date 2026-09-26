"""Stage 1, session 16: the allocation and split rules.

Not a validation case: three deterministic decision rules, each checked
with exact arithmetic. See :mod:`daysofcover.engine.allocation` for the
build plan wording each one implements.
"""

from __future__ import annotations

from daysofcover.engine.allocation import (
    CustomerOrder,
    allocate_by_backlog_proportion,
    allocate_by_margin_priority,
    allocate_finished_goods_to_orders,
    supplier_split_ratios,
)
from daysofcover.models.network import SupplySource


def test_allocate_by_backlog_proportion_splits_by_backlog_share() -> None:
    allocation = allocate_by_backlog_proportion(
        available_quantity=100.0,
        requested_by_sku={"sku-a": 1000.0, "sku-b": 1000.0},
        backlog_by_sku={"sku-a": 30.0, "sku-b": 70.0},
    )

    assert allocation["sku-a"] == 30.0
    assert allocation["sku-b"] == 70.0


def test_allocate_by_backlog_proportion_never_exceeds_a_skus_own_request() -> None:
    # sku-a's backlog share of 100 would be 80, but it only asked for 20.
    allocation = allocate_by_backlog_proportion(
        available_quantity=100.0,
        requested_by_sku={"sku-a": 20.0, "sku-b": 1000.0},
        backlog_by_sku={"sku-a": 80.0, "sku-b": 20.0},
    )

    assert allocation["sku-a"] == 20.0
    # sku-b's own capped share is not topped up with sku-a's unused 60
    assert allocation["sku-b"] == 20.0


def test_allocate_by_backlog_proportion_falls_back_to_an_even_split_with_no_backlog() -> None:
    allocation = allocate_by_backlog_proportion(
        available_quantity=100.0,
        requested_by_sku={"sku-a": 1000.0, "sku-b": 1000.0},
        backlog_by_sku={"sku-a": 0.0, "sku-b": 0.0},
    )

    assert allocation["sku-a"] == 50.0
    assert allocation["sku-b"] == 50.0


def test_allocate_by_margin_priority_serves_highest_margin_first_and_fully() -> None:
    allocation = allocate_by_margin_priority(
        available_quantity=100.0,
        requested_by_sku={"sku-a": 60.0, "sku-b": 60.0, "sku-c": 60.0},
        margin_by_sku={"sku-a": 0.2, "sku-b": 0.5, "sku-c": 0.35},
    )

    # sku-b (highest margin) is served fully first, then sku-c, then
    # sku-a gets whatever is left -- nothing, here.
    assert allocation["sku-b"] == 60.0
    assert allocation["sku-c"] == 40.0
    assert allocation["sku-a"] == 0.0


def test_allocate_finished_goods_to_orders_respects_priority_override() -> None:
    orders = [
        CustomerOrder(customer_id="early-low-priority", order_day=0, quantity=50.0, priority=5),
        CustomerOrder(customer_id="late-high-priority", order_day=10, quantity=50.0, priority=0),
    ]

    fulfilled = allocate_finished_goods_to_orders(available_quantity=50.0, orders=orders)

    # the later order wins because of its priority override, not FIFO by date
    assert fulfilled == [0.0, 50.0]


def test_allocate_finished_goods_to_orders_is_fifo_by_date_within_the_same_priority() -> None:
    orders = [
        CustomerOrder(customer_id="later", order_day=5, quantity=30.0, priority=1),
        CustomerOrder(customer_id="earlier", order_day=1, quantity=30.0, priority=1),
    ]

    fulfilled = allocate_finished_goods_to_orders(available_quantity=30.0, orders=orders)

    # index 1 (order_day=1, "earlier") is served first despite being listed second
    assert fulfilled == [0.0, 30.0]


def test_supplier_split_ratios_unchanged_while_primary_is_up() -> None:
    suppliers = [
        SupplySource(node_id="primary", split_ratio=0.7, is_primary=True, detect_delay_days=3),
        SupplySource(node_id="backup", split_ratio=0.3, is_primary=False),
    ]

    ratios = supplier_split_ratios(
        suppliers=suppliers, primary_down_since_day=None, current_day=100
    )

    assert ratios == {"primary": 0.7, "backup": 0.3}


def test_supplier_split_ratios_unchanged_before_the_detect_delay_elapses() -> None:
    suppliers = [
        SupplySource(node_id="primary", split_ratio=0.7, is_primary=True, detect_delay_days=3),
        SupplySource(node_id="backup", split_ratio=0.3, is_primary=False),
    ]

    ratios = supplier_split_ratios(suppliers=suppliers, primary_down_since_day=10, current_day=12)

    assert ratios == {"primary": 0.7, "backup": 0.3}


def test_supplier_split_ratios_switches_fully_to_the_backup_after_the_delay() -> None:
    suppliers = [
        SupplySource(node_id="primary", split_ratio=0.7, is_primary=True, detect_delay_days=3),
        SupplySource(node_id="backup", split_ratio=0.3, is_primary=False),
    ]

    ratios = supplier_split_ratios(suppliers=suppliers, primary_down_since_day=10, current_day=13)

    assert ratios == {"primary": 0.0, "backup": 1.0}


def test_supplier_split_ratios_renormalises_across_multiple_backups() -> None:
    suppliers = [
        SupplySource(node_id="primary", split_ratio=0.5, is_primary=True, detect_delay_days=2),
        SupplySource(node_id="backup-a", split_ratio=0.3, is_primary=False),
        SupplySource(node_id="backup-b", split_ratio=0.2, is_primary=False),
    ]

    ratios = supplier_split_ratios(suppliers=suppliers, primary_down_since_day=0, current_day=2)

    assert ratios["primary"] == 0.0
    assert ratios["backup-a"] == 0.6
    assert ratios["backup-b"] == 0.4
