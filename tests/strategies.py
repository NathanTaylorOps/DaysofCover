"""Hypothesis strategies for generating valid Days of Cover data.

Property tests (``tests/property/``) check invariants that must hold for
*any* valid input, not just the handful of examples the unit tests pick
by hand. A bare ``st.builds(Network, ...)`` would mostly produce inputs
pydantic rejects before the interesting property is ever exercised -- a
lane's ``origin_id`` pointing nowhere, a part's supplier ``split_ratio``
values not summing to one -- so the strategies below build each kind of
object from the inside out: ids first, then whatever else is only ever
allowed to reference an id already chosen. Every ``Network`` this module
can produce is schema-valid by construction; if it were not, the
``Network(...)`` call in :func:`networks` itself would raise before
Hypothesis ever got a value to hand to a test.

Kept separate from ``tests/property/`` (rather than inside it) so a
non-property test that wants one example of a valid network can import
these strategies too, without importing Hypothesis's test-collection
machinery to get them.
"""

from __future__ import annotations

import hypothesis.strategies as st
from hypothesis import assume

from daysofcover.models.network import (
    Lane,
    LaneMode,
    Network,
    Node,
    NodeType,
    Part,
    SupplySource,
)

_CURRENCIES = ["AUD", "USD", "CNY", "EUR"]
_REGIONS = ["AU", "CN", "US", "DE", "SG"]


def _finite_floats(*, min_value: float, max_value: float) -> st.SearchStrategy[float]:
    return st.floats(
        min_value=min_value, max_value=max_value, allow_nan=False, allow_infinity=False
    )


def unique_ids(prefix: str, *, min_size: int, max_size: int) -> st.SearchStrategy[list[str]]:
    """``min_size`` to ``max_size`` distinct ids, each ``f"{prefix}-{n}"``."""
    return st.lists(
        st.integers(min_value=0, max_value=99_999),
        min_size=min_size,
        max_size=max_size,
        unique=True,
    ).map(lambda ns: [f"{prefix}-{n}" for n in ns])


def _node_for_id(node_id: str) -> st.SearchStrategy[Node]:
    return st.builds(
        Node,
        id=st.just(node_id),
        name=st.just(node_id),
        type=st.sampled_from(list(NodeType)),
        region=st.sampled_from(_REGIONS),
        capacity_per_week=st.none() | _finite_floats(min_value=0.0, max_value=10_000.0),
    )


@st.composite
def supply_sources(
    draw: st.DrawFn, node_ids: list[str], *, max_suppliers: int = 3
) -> list[SupplySource]:
    """A part's supplier list: 1 to ``max_suppliers`` of ``node_ids``, split
    ratios that always sum to exactly 1.0, at most one flagged primary.

    Ratios come from a stick-breaking construction (sorted cut points in
    (0, 1), unique so no gap is exactly zero) rather than normalising
    independent draws, so the sum is exact to within a few ulps rather
    than the schema's 1e-6 tolerance being the thing doing the work.
    """
    n = draw(st.integers(min_value=1, max_value=min(max_suppliers, len(node_ids))))
    supplier_node_ids = draw(
        st.lists(st.sampled_from(node_ids), min_size=n, max_size=n, unique=True)
    )

    if n == 1:
        ratios = [1.0]
    else:
        cuts = sorted(
            draw(
                st.lists(
                    st.floats(
                        min_value=0.0,
                        max_value=1.0,
                        exclude_min=True,
                        exclude_max=True,
                        allow_nan=False,
                        allow_infinity=False,
                    ),
                    min_size=n - 1,
                    max_size=n - 1,
                    unique=True,
                )
            )
        )
        bounds = [0.0, *cuts, 1.0]
        ratios = [bounds[i + 1] - bounds[i] for i in range(n)]
        assume(all(ratio > 1e-9 for ratio in ratios))

    primary_index = draw(st.integers(min_value=0, max_value=n - 1))
    detect_delays = draw(
        st.lists(
            _finite_floats(min_value=0.0, max_value=30.0),
            min_size=n,
            max_size=n,
        )
    )

    return [
        SupplySource(
            node_id=node_id,
            split_ratio=ratio,
            is_primary=(i == primary_index),
            detect_delay_days=delay,
        )
        for i, (node_id, ratio, delay) in enumerate(
            zip(supplier_node_ids, ratios, detect_delays, strict=True)
        )
    ]


@st.composite
def _part_for_id(draw: st.DrawFn, part_id: str, node_ids: list[str]) -> Part:
    return Part(
        id=part_id,
        name=part_id,
        suppliers=draw(supply_sources(node_ids)),
        unit_cost=draw(_finite_floats(min_value=0.0, max_value=1000.0)),
        currency=draw(st.sampled_from(_CURRENCIES)),
    )


@st.composite
def _lane_for_id(draw: st.DrawFn, lane_id: str, node_ids: list[str]) -> Lane:
    origin_id, destination_id = draw(
        st.lists(st.sampled_from(node_ids), min_size=2, max_size=2, unique=True)
    )
    return Lane(
        id=lane_id,
        origin_id=origin_id,
        destination_id=destination_id,
        mode=draw(st.sampled_from(list(LaneMode))),
        lead_time_days_median=draw(_finite_floats(min_value=0.1, max_value=90.0)),
        lead_time_days_sigma=draw(_finite_floats(min_value=0.0, max_value=1.0)),
        capacity_per_week=draw(_finite_floats(min_value=0.0, max_value=10_000.0)),
        unit_cost=draw(_finite_floats(min_value=0.0, max_value=1000.0)),
        currency=draw(st.sampled_from(_CURRENCIES)),
        allow_crossing=draw(st.booleans()),
        moq=draw(st.none() | _finite_floats(min_value=0.0, max_value=500.0)),
    )


@st.composite
def supplier_scenarios(draw: st.DrawFn) -> tuple[list[str], list[SupplySource]]:
    """A node id pool and one part's suppliers drawn from it.

    Everything :func:`daysofcover.engine.allocation.supplier_split_ratios`
    needs, without requiring a caller to build a whole network just to
    get a valid suppliers list.
    """
    node_ids = draw(unique_ids("node", min_size=1, max_size=4))
    return node_ids, draw(supply_sources(node_ids))


@st.composite
def networks(
    draw: st.DrawFn,
    *,
    min_nodes: int = 2,
    max_nodes: int = 6,
    min_parts: int = 0,
    max_parts: int = 4,
    min_lanes: int = 0,
    max_lanes: int = 8,
) -> Network:
    """A schema-valid :class:`~daysofcover.models.network.Network`.

    Every lane's endpoints and every part's supplier node ids are drawn
    from the same node id list, and every part's supplier split ratios
    sum to 1.0, so the ``Network(...)`` construction below always
    succeeds -- there is no ``try/except`` here because a failure would
    mean this strategy itself is wrong, not that the draw was unlucky.
    """
    node_ids = draw(unique_ids("node", min_size=min_nodes, max_size=max_nodes))
    nodes = [draw(_node_for_id(node_id)) for node_id in node_ids]

    part_ids = draw(unique_ids("part", min_size=min_parts, max_size=max_parts))
    parts = [draw(_part_for_id(part_id, node_ids)) for part_id in part_ids]

    lane_ids = draw(unique_ids("lane", min_size=min_lanes, max_size=max_lanes))
    lanes = [draw(_lane_for_id(lane_id, node_ids)) for lane_id in lane_ids]

    return Network(base_currency="AUD", nodes=nodes, lanes=lanes, parts=parts)
