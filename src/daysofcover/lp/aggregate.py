"""The aggregate cover and impact LPs (Simchi-Levi et al. 2015; Gao, Simchi-Levi, Teo and Yan 2019).

Per the build plan: variables ``x_{ij,p}`` (flow of commodity p on lane
i->j over a horizon T), ``u_{i,p}`` (supply or production of p at node
i), ``l_{k,s}`` (lost sales of SKU s at customer k); given ``r_{i,p}``
(on-hand plus in-transit at disruption start), node and lane capacities
per day, the BOM, demand rates, margins and a binary loss factor for
the removed element. Three objectives share the same constraints:
impact minimises money-weighted lost sales at a fixed horizon T; cover
maximises T itself, as a genuine decision variable, subject to zero
lost sales -- linear, not bilinear, because T only ever multiplies
*given constants* (a capacity, a demand rate), never another decision
variable, so no bisection is needed for this flat/aggregate case (only
the later weekly time-indexed variant needs that). Buffer (minimise
holding cost on added inventory subject to zero lost sales) is Stage
2's third LP; it shares this same machinery but isn't built yet --
cases 7, 8 and 9 (this session's targets) never exercise it, so it's
sequenced into a later Stage 2 session along with the weekly
time-indexed/bisection variant, the AND/OR structural screen, and the
``daysofcover cover`` CLI command.

Two deliberate extensions beyond the build plan's literal transcription
of the paper's equations, both flagged here because they're this
implementer's call, same as the max-T formulation itself:

- **Commodities are tagged, not bare strings.** A part id and a SKU id
  share no guaranteed-disjoint namespace in the schema, so every
  commodity is a ``("part", id)`` or ``("sku", id)`` tuple
  (:func:`part_key`/:func:`sku_key`) rather than a raw id -- a lane's
  flow variable and a node's supply/production variable are keyed by
  this tagged form throughout.
- **A demand node's own on-hand counts toward its own demand.** The
  paper's balance constraint (``r + u + inflow - outflow - consumption
  >= 0``) and its demand constraint (``inflow + l = d*T``) are given as
  two separate equations, and the demand equation as transcribed has no
  ``r`` term -- read completely literally, a customer's own
  pre-disruption stock would never reduce its lost sales, only goods
  that arrive *during* the horizon would. That contradicts how this
  project's own engine already works: :mod:`daysofcover.engine.
  daily_step` fulfills an order against whatever ``finished_on_hand``
  sits at that order's own node, plant or customer alike, with no
  special case for which kind of node it is. So here, wherever a
  (node, sku) pair has a real demand rate, the ordinary balance
  inequality at that pair is replaced by one equality that folds
  everything together: ``r + u + inflow - outflow - d*T + l = 0``. This
  is what makes validation case 7's "cover equals the hand-computed
  inventory runway" arithmetic actually come out to a customer's own
  ``r / d`` when it is the last node in the chain -- see the module's
  own test file for the full derivation.

Node and lane capacities are per day (``capacity_per_week / 7``); a
node with no ``capacity_per_week`` at all has no capacity row (nothing
to divide by zero on, nothing to constrain). A removed *node* is
deleted from the graph entirely, along with every lane touching it --
whatever on-hand it held does not carry forward, since the node itself
is gone; a removed *lane* just drops that one lane, leaving its two
endpoints and their own inventory untouched. Both cases 7 and 8 use
this to get an "exact" answer: cutting the one path to a node's own
demand collapses its cover to a plain ``r / d``, with nothing left for
a solver to have to work hard for.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import cast

import numpy as np
from scipy.optimize import OptimizeResult, linprog
from scipy.sparse import csr_matrix

from daysofcover.engine.shipments import NetworkShipments
from daysofcover.engine.state import NetworkState
from daysofcover.models.network import BOMLine, Network, NodeType

CommodityKey = tuple[str, str]


def part_key(part_id: str) -> CommodityKey:
    """Tag a part id as a commodity key -- see the module docstring."""
    return ("part", part_id)


def sku_key(sku_id: str) -> CommodityKey:
    """Tag a SKU id as a commodity key -- see the module docstring."""
    return ("sku", sku_id)


def starting_inventory_from_state(
    *, state: NetworkState, shipments: NetworkShipments
) -> dict[tuple[str, CommodityKey], float]:
    """``r_{i,p}`` read straight off a live DES snapshot: on-hand plus in-transit.

    Call this once, at the moment a disruption starts, to build the
    ``starting_inventory`` argument :func:`solve_impact`/:func:`solve_cover`
    need -- the build plan's own words for case 8 ("LP starting
    inventory from the DES state including in-transit"). Zero-valued
    entries are omitted; a (node, commodity) pair absent from the
    result is exactly the same thing as an explicit zero to the LP
    builder.
    """
    r: dict[tuple[str, CommodityKey], float] = {}
    for node_id in state.node_ids:
        for part_id in state.part_ids:
            quantity = float(
                state.on_hand[state.node_index(node_id), state.part_index(part_id)]
            ) + shipments.outstanding_at_node(node_id=node_id, part_id=part_id)
            if quantity:
                r[(node_id, part_key(part_id))] = quantity
        for sku_id in state.sku_ids:
            quantity = float(
                state.finished_on_hand[state.node_index(node_id), state.sku_index(sku_id)]
            ) + shipments.outstanding_at_node(node_id=node_id, part_id=sku_id)
            if quantity:
                r[(node_id, sku_key(sku_id))] = quantity
    return r


def _fx_rate(currency: str, network: Network) -> float:
    """Units of ``network.base_currency`` per unit of ``currency``."""
    if currency == network.base_currency:
        return 1.0
    try:
        return network.fx_rates[currency]
    except KeyError:
        raise ValueError(
            f"no fx_rate given for currency {currency!r} (base currency is "
            f"{network.base_currency!r})"
        ) from None


@dataclass(frozen=True)
class _ResolvedNetwork:
    """``network`` with ``removed_element_id`` already excluded -- see the module docstring."""

    node_ids: tuple[str, ...]
    lane_ids: tuple[str, ...]
    lanes_into: dict[str, tuple[str, ...]]
    lanes_out_of: dict[str, tuple[str, ...]]
    node_capacity_per_day: dict[str, float]
    lane_capacity_per_day: dict[str, float]
    plant_node_ids: tuple[str, ...]
    part_ids: tuple[str, ...]
    sku_ids: tuple[str, ...]
    part_supplier_nodes: dict[str, tuple[str, ...]]
    bom_by_sku: dict[str, tuple[BOMLine, ...]]
    margin_by_sku: dict[str, float]
    demand_rate: dict[tuple[str, str], float]


def _resolve(network: Network, *, removed_element_id: str | None) -> _ResolvedNetwork:
    excluded_node_ids: set[str] = set()
    excluded_lane_ids: set[str] = set()
    if removed_element_id is not None:
        node_ids_all = {n.id for n in network.nodes}
        lane_ids_all = {ln.id for ln in network.lanes}
        if removed_element_id in node_ids_all:
            excluded_node_ids.add(removed_element_id)
        elif removed_element_id in lane_ids_all:
            excluded_lane_ids.add(removed_element_id)
        else:
            raise ValueError(
                f"removed_element_id {removed_element_id!r} is not a known node or lane id"
            )

    live_nodes = [n for n in network.nodes if n.id not in excluded_node_ids]
    live_node_ids = {n.id for n in live_nodes}
    live_lanes = [
        ln
        for ln in network.lanes
        if ln.id not in excluded_lane_ids
        and ln.origin_id not in excluded_node_ids
        and ln.destination_id not in excluded_node_ids
    ]

    lanes_into: dict[str, list[str]] = {}
    lanes_out_of: dict[str, list[str]] = {}
    lane_capacity_per_day: dict[str, float] = {}
    for lane in live_lanes:
        lanes_into.setdefault(lane.destination_id, []).append(lane.id)
        lanes_out_of.setdefault(lane.origin_id, []).append(lane.id)
        lane_capacity_per_day[lane.id] = lane.capacity_per_week / 7.0

    node_capacity_per_day = {
        n.id: (math.inf if n.capacity_per_week is None else n.capacity_per_week / 7.0)
        for n in live_nodes
    }

    part_supplier_nodes = {
        part.id: tuple(s.node_id for s in part.suppliers if s.node_id in live_node_ids)
        for part in network.parts
    }
    bom_by_sku = {sku.id: tuple(sku.bom) for sku in network.skus}
    margin_by_sku = {
        sku.id: sku.price[sku.currency] * sku.margin_fraction * _fx_rate(sku.currency, network)
        for sku in network.skus
    }

    demand_rate: dict[tuple[str, str], float] = {}
    for customer in network.customers:
        if customer.id not in live_node_ids:
            continue
        for sku_id, profile in customer.demand.items():
            # the aggregate model uses average demand over the horizon,
            # per the build plan -- the weekly multipliers are what the
            # (not-yet-built) time-indexed variant reads instead.
            demand_rate[(customer.id, sku_id)] = profile.base_weekly_rate / 7.0

    return _ResolvedNetwork(
        node_ids=tuple(n.id for n in live_nodes),
        lane_ids=tuple(ln.id for ln in live_lanes),
        lanes_into={k: tuple(v) for k, v in lanes_into.items()},
        lanes_out_of={k: tuple(v) for k, v in lanes_out_of.items()},
        node_capacity_per_day=node_capacity_per_day,
        lane_capacity_per_day=lane_capacity_per_day,
        plant_node_ids=tuple(n.id for n in live_nodes if n.type == NodeType.PLANT),
        part_ids=tuple(p.id for p in network.parts),
        sku_ids=tuple(s.id for s in network.skus),
        part_supplier_nodes=part_supplier_nodes,
        bom_by_sku=bom_by_sku,
        margin_by_sku=margin_by_sku,
        demand_rate=demand_rate,
    )


@dataclass
class _LPBuilder:
    """Column bookkeeping and row accumulation for one solve.

    Every column is created up front; rows accumulate as plain
    ``{column: coefficient}`` dicts and are only assembled into a
    sparse matrix in :meth:`solve` -- cheap to build, and the dict form
    is what lets :func:`_build` add a coefficient to a cell that may or
    may not already have one without a special case either way.
    """

    lower: list[float] = field(default_factory=list)
    upper: list[float] = field(default_factory=list)
    ub_rows: list[dict[int, float]] = field(default_factory=list)
    ub_rhs: list[float] = field(default_factory=list)
    eq_rows: list[dict[int, float]] = field(default_factory=list)
    eq_rhs: list[float] = field(default_factory=list)

    def add_column(self, *, lower: float = 0.0, upper: float = math.inf) -> int:
        col = len(self.lower)
        self.lower.append(lower)
        self.upper.append(upper)
        return col

    def add_le(self, coeffs: dict[int, float], rhs: float) -> None:
        if coeffs:
            self.ub_rows.append(coeffs)
            self.ub_rhs.append(rhs)

    def add_ge(self, coeffs: dict[int, float], rhs: float) -> None:
        """``coeffs . x >= rhs``, rewritten as ``(-coeffs) . x <= -rhs`` for linprog."""
        self.add_le({c: -v for c, v in coeffs.items()}, -rhs)

    def add_eq(self, coeffs: dict[int, float], rhs: float) -> None:
        self.eq_rows.append(coeffs)
        self.eq_rhs.append(rhs)

    def _sparse(self, rows: list[dict[int, float]]) -> csr_matrix:
        n_cols = len(self.lower)
        if not rows:
            return csr_matrix((0, n_cols))
        row_idx: list[int] = []
        col_idx: list[int] = []
        data: list[float] = []
        for r, row in enumerate(rows):
            for c, v in row.items():
                row_idx.append(r)
                col_idx.append(c)
                data.append(v)
        return csr_matrix((data, (row_idx, col_idx)), shape=(len(rows), n_cols))

    def solve(self, objective: dict[int, float], *, maximize: bool) -> OptimizeResult:
        n_cols = len(self.lower)
        c = np.zeros(n_cols)
        for col, coeff in objective.items():
            c[col] = -coeff if maximize else coeff
        bounds = list(zip(self.lower, self.upper, strict=True))
        # scipy-stubs' linprog overloads don't model sparse A_ub/A_eq
        # inputs (csr_matrix) as compatible with their dense-array
        # protocol, even though linprog itself accepts them at runtime
        # for method="highs" -- a known stub gap, not a real type error.
        result = linprog(
            c,
            A_ub=self._sparse(self.ub_rows) if self.ub_rows else None,
            b_ub=np.array(self.ub_rhs) if self.ub_rhs else None,
            A_eq=self._sparse(self.eq_rows) if self.eq_rows else None,
            b_eq=np.array(self.eq_rhs) if self.eq_rhs else None,
            bounds=bounds,
            method="highs",
        )  # type: ignore[call-overload]
        return cast(OptimizeResult, result)


@dataclass(frozen=True)
class _Columns:
    x: dict[tuple[str, CommodityKey], int]
    u: dict[tuple[str, CommodityKey], int]
    lost: dict[tuple[str, str], int]
    t: int | None


def _t_rhs(
    row: dict[int, float], coeff: float, *, t_fixed: float | None, t_col: int | None
) -> float:
    """Fold ``coeff * T`` into ``row`` (as ``-coeff`` on ``t_col``) or return it as a constant.

    Every row that depends on the horizon uses this the same way: with
    T fixed (the impact LP), the term is just a number that ends up on
    the RHS; with T itself a column (the cover LP), the term becomes
    ``-coeff`` on that column, folded into ``row`` in place, and the
    returned constant is 0 since there's nothing left to move.
    """
    if t_fixed is not None:
        return coeff * t_fixed
    assert t_col is not None
    row[t_col] = row.get(t_col, 0.0) - coeff
    return 0.0


def _build(
    resolved: _ResolvedNetwork,
    *,
    starting_inventory: dict[tuple[str, CommodityKey], float],
    t_fixed: float | None,
) -> tuple[_LPBuilder, _Columns]:
    """Every column and row shared by the impact and cover LPs.

    ``t_fixed`` is the horizon in days for the impact LP; ``None`` means
    the cover LP, where T is a column in its own right
    (:attr:`_Columns.t`) instead of a given number.
    """
    b = _LPBuilder()
    commodities: list[CommodityKey] = [part_key(p) for p in resolved.part_ids] + [
        sku_key(s) for s in resolved.sku_ids
    ]

    x_cols: dict[tuple[str, CommodityKey], int] = {
        (lane_id, commodity): b.add_column()
        for lane_id in resolved.lane_ids
        for commodity in commodities
    }

    u_cols: dict[tuple[str, CommodityKey], int] = {}
    for part_id, supplier_nodes in resolved.part_supplier_nodes.items():
        for node_id in supplier_nodes:
            u_cols[(node_id, part_key(part_id))] = b.add_column()
    for sku_id in resolved.sku_ids:
        for node_id in resolved.plant_node_ids:
            u_cols[(node_id, sku_key(sku_id))] = b.add_column()

    # cover pins lost sales at exactly zero rather than omitting l
    # entirely, so the same row-building code below works unchanged for
    # both LPs -- see _t_rhs for the other half of that symmetry.
    l_upper = math.inf if t_fixed is not None else 0.0
    l_cols: dict[tuple[str, str], int] = {
        pair: b.add_column(upper=l_upper) for pair in resolved.demand_rate
    }

    t_col = b.add_column() if t_fixed is None else None

    consuming_skus_by_part: dict[str, list[tuple[str, float]]] = {}
    for sku_id, bom_lines in resolved.bom_by_sku.items():
        for line in bom_lines:
            consuming_skus_by_part.setdefault(line.part_id, []).append((sku_id, line.quantity))

    for node_id in resolved.node_ids:
        for commodity in commodities:
            row: dict[int, float] = {}
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

            r_value = starting_inventory.get((node_id, commodity), 0.0)
            demand_key = (node_id, commodity_id) if kind == "sku" else None
            rate = resolved.demand_rate.get(demand_key) if demand_key is not None else None

            if rate is None:
                if row:
                    b.add_ge(row, -r_value)
                continue

            # a demand node's own on-hand folds directly into the
            # equality, rather than a separate slack inequality -- see
            # the module docstring's second extension.
            l_col = l_cols[demand_key]  # type: ignore[index]
            row[l_col] = row.get(l_col, 0.0) + 1.0
            rhs = _t_rhs(row, rate, t_fixed=t_fixed, t_col=t_col) - r_value
            b.add_eq(row, rhs)

    for node_id in resolved.node_ids:
        cap = resolved.node_capacity_per_day[node_id]
        if math.isinf(cap):
            continue
        row = {}
        for commodity in commodities:
            u_col_here = u_cols.get((node_id, commodity))
            if u_col_here is not None:
                row[u_col_here] = row.get(u_col_here, 0.0) + 1.0
        if not row:
            continue
        rhs = _t_rhs(row, cap, t_fixed=t_fixed, t_col=t_col)
        b.add_le(row, rhs)

    for lane_id in resolved.lane_ids:
        row = {x_cols[(lane_id, commodity)]: 1.0 for commodity in commodities}
        rhs = _t_rhs(row, resolved.lane_capacity_per_day[lane_id], t_fixed=t_fixed, t_col=t_col)
        b.add_le(row, rhs)

    return b, _Columns(x=x_cols, u=u_cols, lost=l_cols, t=t_col)


@dataclass(frozen=True)
class ImpactResult:
    status: str
    total_impact: float
    lost_sales_by_customer_sku: dict[tuple[str, str], float]


def solve_impact(
    network: Network,
    *,
    removed_element_id: str | None,
    horizon_days: float,
    starting_inventory: dict[tuple[str, CommodityKey], float],
) -> ImpactResult:
    """The impact LP: minimise money-weighted lost sales at a fixed horizon.

    ``horizon_days`` is normally ``recovery_e(P80)`` -- computing that
    estimate is a caller's job (the hazard/recovery layer, not yet
    built); this function only solves the LP for whatever ``T`` it is
    given, fixed.
    """
    resolved = _resolve(network, removed_element_id=removed_element_id)
    builder, columns = _build(resolved, starting_inventory=starting_inventory, t_fixed=horizon_days)
    objective = {
        col: resolved.margin_by_sku[sku_id] for (_customer_id, sku_id), col in columns.lost.items()
    }
    result = builder.solve(objective, maximize=False)
    if not result.success:
        return ImpactResult(
            status=result.message, total_impact=math.nan, lost_sales_by_customer_sku={}
        )
    lost_sales = {key: float(result.x[col]) for key, col in columns.lost.items()}
    return ImpactResult(
        status="optimal", total_impact=float(result.fun), lost_sales_by_customer_sku=lost_sales
    )


@dataclass(frozen=True)
class CoverResult:
    status: str
    cover_days: float


def solve_cover(
    network: Network,
    *,
    removed_element_id: str | None,
    starting_inventory: dict[tuple[str, CommodityKey], float],
) -> CoverResult:
    """The cover LP: maximise the horizon T over which every order still ships in full.

    T is a genuine decision variable here (see the module docstring for
    why that stays linear), not something bisected over.
    """
    resolved = _resolve(network, removed_element_id=removed_element_id)
    builder, columns = _build(resolved, starting_inventory=starting_inventory, t_fixed=None)
    assert columns.t is not None
    result = builder.solve({columns.t: 1.0}, maximize=True)
    if result.status == 3:  # unbounded -- nothing in the network ever runs out
        return CoverResult(status="unbounded", cover_days=math.inf)
    if not result.success:
        return CoverResult(status=result.message, cover_days=math.nan)
    return CoverResult(status="optimal", cover_days=float(result.x[columns.t]))
