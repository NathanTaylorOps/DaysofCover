"""Allocation policies for constrained components, finished goods and sourcing.

Shared components can be allocated to SKUs in proportion to backlog or
according to margin priority. Scarce finished goods can be assigned to
customer orders using FIFO with a priority override. Dual-source
replenishment supports fixed allocation ratios and a contingent switch
to the backup supplier after the configured detection delay.

These functions implement independent allocation decisions. The daily-step
engine supplies current demand, inventory and disruption context and
coordinates their execution.
"""

from __future__ import annotations

from dataclasses import dataclass

from daysofcover.models.network import SupplySource


def allocate_by_backlog_proportion(
    *,
    available_quantity: float,
    requested_by_sku: dict[str, float],
    backlog_by_sku: dict[str, float],
) -> dict[str, float]:
    """Split a scarce component across SKUs, weighted by each one's backlog.

    A SKU never gets more than it asked for (``requested_by_sku``), but
    a SKU capped this way does not have its unused share redistributed
    to the others in this same call -- the next call, once backlogs
    have moved, allocates the (now smaller) remainder among whoever is
    still short. If every requesting SKU has zero backlog, the split
    falls back to an even share among them, since a backlog-weighted
    average of all zeros is undefined.
    """
    total_backlog = sum(backlog_by_sku.get(sku, 0.0) for sku in requested_by_sku)

    if total_backlog <= 0:
        requesting = [sku for sku, quantity in requested_by_sku.items() if quantity > 0]
        if not requesting:
            return {sku: 0.0 for sku in requested_by_sku}
        even_share = available_quantity / len(requesting)
        return {
            sku: (min(requested_by_sku[sku], even_share) if sku in requesting else 0.0)
            for sku in requested_by_sku
        }

    return {
        sku: min(
            requested_by_sku[sku],
            available_quantity * backlog_by_sku.get(sku, 0.0) / total_backlog,
        )
        for sku in requested_by_sku
    }


def allocate_by_margin_priority(
    *,
    available_quantity: float,
    requested_by_sku: dict[str, float],
    margin_by_sku: dict[str, float],
) -> dict[str, float]:
    """Split a scarce component across SKUs, highest margin served first.

    The margin-priority option named alongside backlog proportion in
    the build plan: each SKU in descending margin order gets its full
    request before the next SKU gets anything, until supply runs out.
    A SKU missing from ``margin_by_sku`` is treated as margin zero, so
    it is served last, not skipped.
    """
    allocation = {sku: 0.0 for sku in requested_by_sku}
    remaining = available_quantity

    for sku in sorted(requested_by_sku, key=lambda s: margin_by_sku.get(s, 0.0), reverse=True):
        take = min(requested_by_sku[sku], remaining)
        allocation[sku] = take
        remaining -= take

    return allocation


@dataclass(frozen=True)
class CustomerOrder:
    """One customer's outstanding order for a scarce finished good."""

    customer_id: str
    order_day: int
    quantity: float
    priority: int
    """Lower is served first -- the override on plain FIFO-by-date."""


def allocate_finished_goods_to_orders(
    *, available_quantity: float, orders: list[CustomerOrder]
) -> list[float]:
    """Fulfilled quantity per order, in the same order as ``orders``.

    Orders are served by ascending priority first (0 first), then FIFO
    by ``order_day`` within the same priority -- the override the build
    plan names is on priority, not date; two orders at equal priority
    still queue by date, oldest first.
    """
    service_order = sorted(
        range(len(orders)), key=lambda i: (orders[i].priority, orders[i].order_day)
    )
    fulfilled = [0.0] * len(orders)
    remaining = available_quantity

    for i in service_order:
        take = min(orders[i].quantity, remaining)
        fulfilled[i] = take
        remaining -= take

    return fulfilled


def supplier_split_ratios(
    *,
    suppliers: list[SupplySource],
    primary_down_since_day: int | None,
    current_day: int,
) -> dict[str, float]:
    """Fraction of a new order routed to each of a part's suppliers.

    Normally every supplier's own ``split_ratio`` is used unchanged.
    Once the primary has been known down for at least its own
    ``detect_delay_days`` (``current_day - primary_down_since_day >=
    detect_delay_days``), every ratio is renormalised across the
    remaining (non-primary) suppliers only, so the whole order goes to
    the backup or backups -- a contingent *full* switch, matching the
    plan's own wording, not a gradual shift. If the part has no
    supplier flagged ``is_primary``, or the primary has no backup to
    switch to, the original ratios are returned unchanged.
    """
    primary = next((supplier for supplier in suppliers if supplier.is_primary), None)
    switched = (
        primary is not None
        and primary_down_since_day is not None
        and current_day - primary_down_since_day >= primary.detect_delay_days
    )

    if not switched:
        return {supplier.node_id: supplier.split_ratio for supplier in suppliers}

    backups = [supplier for supplier in suppliers if not supplier.is_primary]
    if not backups:
        return {supplier.node_id: supplier.split_ratio for supplier in suppliers}

    backup_total = sum(supplier.split_ratio for supplier in backups)
    return {
        supplier.node_id: (0.0 if supplier.is_primary else supplier.split_ratio / backup_total)
        for supplier in suppliers
    }
