"""The AND/OR structural screen (build plan section 5, "Structural screen").

A screen, never a score: ordinary centrality measures (degree, betweenness,
PageRank) have no empirical support for predicting disruption impact on a
BOM network, because a SKU needs *every* part in its bill of materials from
*some* qualified supplier -- an AND across parts, an OR across suppliers,
not a path-reachability question. Per the build plan: element *e* is a
chokepoint for (customer *k*, SKU *s*) if, with *e* removed, some part in
BOM(*s*) has no supplier with a path to *the* plant, or the plant has no
path to *k*.

**Implementer's call, flagged same as the aggregate LP module's own two
extensions**: this project's schema allows more than one live plant (any
surviving :class:`~daysofcover.models.network.NodeType.PLANT` node can, per
the aggregate LP's own design decision, produce any SKU it has parts for),
so "the plant" is read as "some one plant that the whole BOM converges on" --
(*k*, *s*) survives *e*'s removal iff there exists at least one live plant
*P* such that every part in BOM(*s*) has a live supplier with a path to *P*,
**and** *P* itself has a path to *k*. With exactly one plant in the network
(every case built so far), this collapses to the plan's own words exactly.

Convergence fraction of *e* = the value of the (customer, SKU) pairs it
cuts, divided by the value of all of them. "Value" isn't specified by the
build plan beyond "value of the (k, s) pairs" -- read here as each pair's
revenue rate, ``margin_by_sku[s] * demand_rate[(k, s)]``, the same figures
:mod:`daysofcover.lp.aggregate` already computes for the impact LP's own
objective. Both the survival check and the value weights are computed
against the *undisrupted* network, once, so that convergence fractions
across every candidate element share the same fixed denominator and the
same fixed set of (k, s) pairs to test -- removing *e* only ever changes
which of those fixed pairs still have a surviving path, never the set
itself or its weights. Reachability is structural only: no capacity, no
lead time, no quantity -- exactly what "a screen, never a score" means.

Implemented as a small BFS over the resolved graph, no solver involved.
"""

from __future__ import annotations

from dataclasses import dataclass

from daysofcover.lp.aggregate import _resolve, _ResolvedNetwork
from daysofcover.models.network import Network


def _adjacency(resolved: _ResolvedNetwork) -> dict[str, set[str]]:
    """Forward node->node reachability for one hop, from the resolved graph.

    ``lanes_into``/``lanes_out_of`` are both keyed by node and list lane
    ids; a lane's destination is whichever node has it in ``lanes_into``,
    so that's enough to build direct-neighbour sets without needing the
    raw :class:`~daysofcover.models.network.Lane` objects at all.
    """
    destination_of: dict[str, str] = {}
    for node_id, lane_ids in resolved.lanes_into.items():
        for lane_id in lane_ids:
            destination_of[lane_id] = node_id

    adjacency: dict[str, set[str]] = {node_id: set() for node_id in resolved.node_ids}
    for node_id, lane_ids in resolved.lanes_out_of.items():
        for lane_id in lane_ids:
            destination = destination_of.get(lane_id)
            if destination is not None:
                adjacency[node_id].add(destination)
    return adjacency


def _reachable_from(start: str, adjacency: dict[str, set[str]]) -> set[str]:
    seen = {start}
    stack = [start]
    while stack:
        current = stack.pop()
        for neighbour in adjacency.get(current, ()):
            if neighbour not in seen:
                seen.add(neighbour)
                stack.append(neighbour)
    return seen


def _sku_survives(
    resolved: _ResolvedNetwork, *, sku_id: str, customer_id: str, adjacency: dict[str, set[str]]
) -> bool:
    if customer_id not in resolved.node_ids:
        return False  # the customer itself was removed

    for plant_id in resolved.plant_node_ids:
        if customer_id not in _reachable_from(plant_id, adjacency):
            continue
        every_part_reaches_this_plant = True
        for line in resolved.bom_by_sku.get(sku_id, ()):
            suppliers = resolved.part_supplier_nodes.get(line.part_id, ())
            if not any(
                plant_id in _reachable_from(supplier_id, adjacency) for supplier_id in suppliers
            ):
                every_part_reaches_this_plant = False
                break
        if every_part_reaches_this_plant:
            return True
    return False


@dataclass(frozen=True)
class ScreenResult:
    convergence_fraction: float
    cut_pairs: tuple[tuple[str, str], ...]


def structural_convergence(network: Network, *, removed_element_id: str) -> ScreenResult:
    """How much (customer, SKU) revenue-rate value ``removed_element_id`` cuts.

    Computes every (customer, SKU) pair and its value once from the
    undisrupted network, then checks which of those fixed pairs lose every
    supplier-to-plant-to-customer path once ``removed_element_id`` is gone.
    """
    baseline = _resolve(network, removed_element_id=None)
    pairs_and_values = {
        pair: baseline.margin_by_sku[pair[1]] * rate for pair, rate in baseline.demand_rate.items()
    }
    total_value = sum(pairs_and_values.values())

    resolved = _resolve(network, removed_element_id=removed_element_id)
    adjacency = _adjacency(resolved)

    cut_pairs = tuple(
        pair
        for pair in pairs_and_values
        if not _sku_survives(resolved, sku_id=pair[1], customer_id=pair[0], adjacency=adjacency)
    )
    cut_value = sum(pairs_and_values[pair] for pair in cut_pairs)
    fraction = cut_value / total_value if total_value else 0.0
    return ScreenResult(convergence_fraction=fraction, cut_pairs=cut_pairs)
