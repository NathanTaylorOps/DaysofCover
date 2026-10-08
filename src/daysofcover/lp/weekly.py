"""The weekly time-indexed cover variant, with bisection on T and the
worst start week (build plan section 4: "a weekly time-indexed variant
with per-week demand satisfaction runs for the top elements and the
selected start week, with bisection on T (at most six solves per
element); cover is reported per element as the minimum over start weeks
with the worst week labelled").

The flat aggregate LP (:mod:`daysofcover.lp.aggregate`) treats demand as
one average rate over the whole horizon, which hides seasonality
entirely -- a network that can comfortably absorb a *year's average*
weekly demand can still run out mid-way through a real peak season. This
module checks week by week instead, using each SKU's own
``SeasonalDemandProfile.weekly_multipliers`` directly rather than the
flat model's ``base_weekly_rate / 7``, and tracks ending inventory
``r_w`` as an explicit variable carried from week to week (``r_w = r_{w-1}
+ net_flow_w``, with ``r_w``'s own non-negativity bound doing the "nothing
ran out yet" work) rather than the flat model's folded single-equation
trick -- there is no equivalent bug to the one that trick had, because
``r_w`` is a real, bounded variable here, not a fixed constant appearing
on both sides of one equation.

Cover, at this granularity, is no longer a free LP column: with a
different weekly multiplier every week, "maximise T subject to zero lost
sales" is not linear in T the way the flat model's flat-rate cover LP
is (T only ever multiplied *given constants* there; here the *set* of
constants used changes with T itself, since a longer horizon pulls in
different weeks' multipliers). So T is found by integer bisection
instead: solve a plain feasibility LP (a zero objective; only
``result.success`` matters) at a candidate week count, and narrow the
search the way the build plan says -- at most six solves per element.
``MAX_WEEKS_SEARCHED = 32`` is chosen so a plain bisection needs exactly
five solves plus one to check the upper bound is itself feasible (a
network that survives 32 straight weeks with zero lost sales is reported
as "at least 32 weeks", a documented cap rather than a claim of literal
infinite cover -- resolving that properly would mean detecting a
steady-state cycle across the full 52-week seasonal pattern, which is
future work, not this session's).

Node and lane exclusion for a removed element reuses
:func:`daysofcover.lp.aggregate._resolve` directly, since which nodes and
lanes survive a removal has nothing to do with daily-versus-weekly
granularity -- only the capacity *units* differ, and
``node_capacity_per_day`` / ``lane_capacity_per_day`` convert back to
weekly figures by multiplying by 7 (exact by construction, since that
division is exactly how :func:`_resolve` built them from the schema's own
native ``capacity_per_week`` fields in the first place).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from daysofcover.lp.aggregate import (
    CommodityKey,
    _LPBuilder,
    _resolve,
    _ResolvedNetwork,
    part_key,
    sku_key,
)
from daysofcover.models.network import Network


class WeeklyCoverSolverError(RuntimeError):
    """An LP run ended without a reliable feasibility determination."""

MAX_WEEKS_SEARCHED = 32
WEEKS_PER_YEAR = 52


def _weekly_capacity(daily_capacity: float) -> float:
    return daily_capacity if math.isinf(daily_capacity) else daily_capacity * 7.0


def _weekly_demand_rates(
    network: Network, *, live_node_ids: frozenset[str]
) -> dict[tuple[str, str], tuple[float, ...]]:
    """Every live (customer, sku) pair's own 52 weekly rates, base_weekly_rate * multiplier."""
    rates: dict[tuple[str, str], tuple[float, ...]] = {}
    for customer in network.customers:
        if customer.id not in live_node_ids:
            continue
        for sku_id, profile in customer.demand.items():
            rates[(customer.id, sku_id)] = tuple(
                profile.base_weekly_rate * m for m in profile.weekly_multipliers
            )
    return rates


def _build_weekly(
    resolved: _ResolvedNetwork,
    weekly_demand_rates: dict[tuple[str, str], tuple[float, ...]],
    *,
    starting_inventory: dict[tuple[str, CommodityKey], float],
    n_weeks: int,
    start_week: int,
) -> _LPBuilder:
    """One feasibility LP: can every week 0..n_weeks-1 be satisfied with zero lost sales?"""
    b = _LPBuilder()
    commodities: list[CommodityKey] = [part_key(p) for p in resolved.part_ids] + [
        sku_key(s) for s in resolved.sku_ids
    ]
    node_cap = {n: _weekly_capacity(c) for n, c in resolved.node_capacity_per_day.items()}
    lane_cap = {ln: _weekly_capacity(c) for ln, c in resolved.lane_capacity_per_day.items()}

    consuming_skus_by_part: dict[str, list[tuple[str, float]]] = {}
    for sku_id, bom_lines in resolved.bom_by_sku.items():
        for line in bom_lines:
            consuming_skus_by_part.setdefault(line.part_id, []).append((sku_id, line.quantity))

    # r_cols[w] holds the ending-inventory column for week w (0-indexed);
    # "week -1" is starting_inventory itself, a constant, not a column.
    r_cols: list[dict[tuple[str, CommodityKey], int]] = []

    for week in range(n_weeks):
        x_cols = {
            (lane_id, commodity): b.add_column()
            for lane_id in resolved.lane_ids
            for commodity in commodities
        }
        u_cols: dict[tuple[str, CommodityKey], int] = {}
        for part_id, supplier_nodes in resolved.part_supplier_nodes.items():
            for node_id in supplier_nodes:
                cap = node_cap[node_id]
                u_cols[(node_id, part_key(part_id))] = b.add_column(upper=cap)
        for sku_id in resolved.sku_ids:
            for node_id in resolved.plant_node_ids:
                cap = node_cap[node_id]
                u_cols[(node_id, sku_key(sku_id))] = b.add_column(upper=cap)

        this_week_r: dict[tuple[str, CommodityKey], int] = {
            (node_id, commodity): b.add_column()
            for node_id in resolved.node_ids
            for commodity in commodities
        }

        for node_id in resolved.node_ids:
            for commodity in commodities:
                row: dict[int, float] = {this_week_r[(node_id, commodity)]: -1.0}
                u_col = u_cols.get((node_id, commodity))
                if u_col is not None:
                    row[u_col] = row.get(u_col, 0.0) + 1.0
                for lane_id in resolved.lanes_into.get(node_id, ()):
                    col = x_cols[(lane_id, commodity)]
                    row[col] = row.get(col, 0.0) + 1.0
                for lane_id in resolved.lanes_out_of.get(node_id, ()):
                    col = x_cols[(lane_id, commodity)]
                    row[col] = row.get(col, 0.0) - 1.0

                kind, commodity_id = commodity
                if kind == "part":
                    for sku_id, bom_quantity in consuming_skus_by_part.get(commodity_id, ()):
                        sku_u_col = u_cols.get((node_id, sku_key(sku_id)))
                        if sku_u_col is not None:
                            row[sku_u_col] = row.get(sku_u_col, 0.0) - bom_quantity

                previous_r = r_cols[week - 1].get((node_id, commodity)) if week > 0 else None
                if previous_r is not None:
                    row[previous_r] = row.get(previous_r, 0.0) + 1.0
                    previous_r_constant = 0.0
                else:
                    previous_r_constant = starting_inventory.get((node_id, commodity), 0.0)

                # row so far is "-r_w + net_flow_w [+ r_{w-1}, if a
                # column]"; a constant r_{w-1} (week 0 only) stays on the
                # LHS conceptually and so flips sign crossing to the RHS
                # -- rhs = -previous_r_constant, not +previous_r_constant.
                demand_key = (node_id, commodity_id) if kind == "sku" else None
                weekly_rates = weekly_demand_rates.get(demand_key) if demand_key else None
                if weekly_rates is None:
                    # r_w - r_{w-1} - net_flow_w = 0
                    b.add_eq(row, -previous_r_constant)
                    continue

                # every demand pair gets a lost-sales column pinned to
                # zero -- this module only ever answers "is zero lost
                # sales feasible", never how much would be lost.
                l_col = b.add_column(upper=0.0)
                row[l_col] = row.get(l_col, 0.0) + 1.0
                calendar_week = (start_week + week) % WEEKS_PER_YEAR
                # r_w - r_{w-1} - net_flow_w + demand_w - l_w = 0, so
                # -r_w + net_flow_w [+ r_{w-1}] + l_w = demand_w - previous_r_constant.
                b.add_eq(row, weekly_rates[calendar_week] - previous_r_constant)

        r_cols.append(this_week_r)

        for lane_id in resolved.lane_ids:
            row = {x_cols[(lane_id, commodity)]: 1.0 for commodity in commodities}
            b.add_le(row, lane_cap[lane_id])

    return b


def _feasible(
    resolved: _ResolvedNetwork,
    weekly_demand_rates: dict[tuple[str, str], tuple[float, ...]],
    *,
    starting_inventory: dict[tuple[str, CommodityKey], float],
    n_weeks: int,
    start_week: int,
) -> bool:
    if n_weeks == 0:
        return True  # an empty horizon is vacuously fine
    builder = _build_weekly(
        resolved,
        weekly_demand_rates,
        starting_inventory=starting_inventory,
        n_weeks=n_weeks,
        start_week=start_week,
    )
    result = builder.solve({}, maximize=False)
    if result.status == 0 and result.success:
        return True
    if result.status == 2:
        return False
    raise WeeklyCoverSolverError(
        f"Weekly cover feasibility solve failed (status={result.status}): {result.message}"
    )


def _max_feasible_weeks(
    resolved: _ResolvedNetwork,
    weekly_demand_rates: dict[tuple[str, str], tuple[float, ...]],
    *,
    starting_inventory: dict[tuple[str, CommodityKey], float],
    start_week: int,
) -> int:
    """The largest ``n_weeks`` (up to :data:`MAX_WEEKS_SEARCHED`) with zero lost sales."""
    if _feasible(
        resolved,
        weekly_demand_rates,
        starting_inventory=starting_inventory,
        n_weeks=MAX_WEEKS_SEARCHED,
        start_week=start_week,
    ):
        return MAX_WEEKS_SEARCHED

    lo, hi = 0, MAX_WEEKS_SEARCHED  # invariant: lo is feasible, hi is not (checked above)
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if _feasible(
            resolved,
            weekly_demand_rates,
            starting_inventory=starting_inventory,
            n_weeks=mid,
            start_week=start_week,
        ):
            lo = mid
        else:
            hi = mid
    return lo


@dataclass(frozen=True)
class WeeklyCoverResult:
    cover_weeks: int
    worst_start_week: int
    at_cap: bool


def solve_weekly_cover(
    network: Network,
    *,
    removed_element_id: str | None,
    starting_inventory: dict[tuple[str, CommodityKey], float],
    start_weeks: range = range(WEEKS_PER_YEAR),
) -> WeeklyCoverResult:
    """Cover in whole weeks, seasonality-aware: the minimum over every start week.

    ``start_weeks`` defaults to the full year (0..51, matching the build
    plan's own "worst start week"), but a caller may narrow it -- both
    for a cheaper query and because the bisection's own six solves per
    start week make the full sweep the most expensive call in this
    module (up to 52 * 6 solves for one element).
    """
    resolved = _resolve(network, removed_element_id=removed_element_id)
    live_node_ids = frozenset(resolved.node_ids)
    weekly_demand_rates = _weekly_demand_rates(network, live_node_ids=live_node_ids)

    worst_weeks: int | None = None
    worst_start_week = 0
    for start_week in start_weeks:
        weeks = _max_feasible_weeks(
            resolved,
            weekly_demand_rates,
            starting_inventory=starting_inventory,
            start_week=start_week,
        )
        if worst_weeks is None or weeks < worst_weeks:
            worst_weeks = weeks
            worst_start_week = start_week

    assert worst_weeks is not None  # start_weeks is never empty in practice
    return WeeklyCoverResult(
        cover_weeks=worst_weeks,
        worst_start_week=worst_start_week,
        at_cap=worst_weeks == MAX_WEEKS_SEARCHED,
    )
