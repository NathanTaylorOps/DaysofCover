"""Route finished goods from production sites to customer-facing nodes.

A distribution tree maps configured outbound lanes from one plant to its
reachable customers. Each lane uses the existing shipment model, including
lead times, weekly capacity, minimum order quantities and disruption state.

The route is deliberately a tree rather than a general graph: each
reachable node has one upstream path. Ambiguous alternate paths are
rejected rather than selected implicitly.

Outbound movement uses a push policy. Available finished goods are
allocated across downstream branches according to outstanding demand and
then constrained by the corresponding lane. This is distinct from the
inbound component replenishment policy, which targets inventory position.

For networks without customer-typed nodes, the distribution tree is empty.
The daily-step engine can then fulfil demand directly from plant inventory,
preserving compatibility with networks that omit outbound distribution.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from daysofcover.engine.disruption_state import DisruptionState
from daysofcover.engine.shipments import NetworkShipments, cap_order_quantity
from daysofcover.engine.state import NetworkState
from daysofcover.models.network import Network, NodeType


@dataclass(frozen=True)
class DistributionTree:
    """One plant's real distribution network, resolved once from ``Network.lanes``.

    ``path_by_customer`` maps each customer id whose own node is
    reachable from the plant to the ordered lane ids from the plant to
    it. ``outbound_lanes_by_node`` and ``inbound_lane_by_node`` are the
    same tree read node by node: every node's outbound lanes (toward
    its children) and its one inbound lane (``None`` only for the
    plant itself, the tree's root). ``nodes_in_push_order`` visits the
    plant first, then every other node on the tree in breadth-first
    order, so a node's own inbound lane is always received before that
    node's outbound push is computed -- see :func:`push_finished_goods`.
    ``customers_downstream_of_lane`` is every customer reachable
    through a given lane, the weighting signal a push split needs.

    A customer id absent from ``path_by_customer`` (its own node
    doesn't exist, or the network has no distribution lanes at all) is
    not a failure -- callers fall back to fulfilling that customer's
    orders at the plant directly, exactly as every session before this
    one always did.
    """

    plant_node_id: str
    path_by_customer: dict[str, tuple[str, ...]]
    outbound_lanes_by_node: dict[str, tuple[str, ...]]
    inbound_lane_by_node: dict[str, str]
    nodes_in_push_order: tuple[str, ...]
    customers_downstream_of_lane: dict[str, tuple[str, ...]]


def build_distribution_tree(network: Network, *, plant_node_id: str) -> DistributionTree:
    """Resolve ``network``'s real lanes into one plant's distribution tree.

    Raises :class:`ValueError` if a node is reachable from the plant by
    more than one path -- see the module docstring for why this module
    holds itself to the tree assumption rather than picking one path
    arbitrarily.
    """
    lanes_by_origin: dict[str, list[str]] = {}
    for lane in network.lanes:
        lanes_by_origin.setdefault(lane.origin_id, []).append(lane.id)
    lane_by_id = {lane.id: lane for lane in network.lanes}

    customer_node_ids = {node.id for node in network.nodes if node.type == NodeType.CUSTOMER}

    path_to_node: dict[str, tuple[str, ...]] = {plant_node_id: ()}
    queue: deque[str] = deque([plant_node_id])
    while queue:
        node_id = queue.popleft()
        for lane_id in lanes_by_origin.get(node_id, []):
            destination_id = lane_by_id[lane_id].destination_id
            if destination_id in path_to_node:
                raise ValueError(
                    f"node {destination_id!r} is reachable from plant {plant_node_id!r} by "
                    "more than one path -- distribution routing assumes a tree"
                )
            path_to_node[destination_id] = path_to_node[node_id] + (lane_id,)
            queue.append(destination_id)

    path_by_customer = {
        node_id: path
        for node_id, path in path_to_node.items()
        if node_id in customer_node_ids and path
    }

    relevant_lane_ids: set[str] = set()
    for path in path_by_customer.values():
        relevant_lane_ids.update(path)

    outbound_lanes_by_node: dict[str, list[str]] = {}
    inbound_lane_by_node: dict[str, str] = {}
    for lane_id in relevant_lane_ids:
        lane = lane_by_id[lane_id]
        outbound_lanes_by_node.setdefault(lane.origin_id, []).append(lane_id)
        inbound_lane_by_node[lane.destination_id] = lane_id

    customers_downstream_of_lane: dict[str, list[str]] = {}
    for customer_id, path in path_by_customer.items():
        for lane_id in path:
            customers_downstream_of_lane.setdefault(lane_id, []).append(customer_id)

    order = [plant_node_id]
    seen = {plant_node_id}
    bfs: deque[str] = deque([plant_node_id])
    while bfs:
        node_id = bfs.popleft()
        for lane_id in outbound_lanes_by_node.get(node_id, ()):
            destination_id = lane_by_id[lane_id].destination_id
            if destination_id not in seen:
                seen.add(destination_id)
                order.append(destination_id)
                bfs.append(destination_id)

    return DistributionTree(
        plant_node_id=plant_node_id,
        path_by_customer=path_by_customer,
        outbound_lanes_by_node={k: tuple(v) for k, v in outbound_lanes_by_node.items()},
        inbound_lane_by_node=inbound_lane_by_node,
        nodes_in_push_order=tuple(order),
        customers_downstream_of_lane={k: tuple(v) for k, v in customers_downstream_of_lane.items()},
    )


def push_finished_goods(
    *,
    state: NetworkState,
    shipments: NetworkShipments,
    tree: DistributionTree,
    sku_id: str,
    current_day: int,
    rng: np.random.Generator | None = None,
    disruption_state: DisruptionState | None = None,
) -> float:
    """Move one SKU's on-hand one hop further down ``tree``, at every node, today.

    Call this once per SKU per day, after that SKU's production has
    completed and before any customer order is fulfilled against a
    distribution node's own on-hand -- see
    :mod:`daysofcover.engine.daily_step` for where it fits in the day's
    order of operations. Returns the total quantity shipped across the
    whole tree today (for reporting only; callers do not need it to
    keep state correct).

    A fully down lane (``disruption_state``) holds whatever has
    already arrived rather than releasing it, exactly like the inbound
    component side; a partially down lane throttles this shipment's
    capacity the same way. Neither ever loses a unit already in
    transit -- it only delays when it lands.
    """
    total_shipped = 0.0
    sku_idx = state.sku_index(sku_id)

    for node_id in tree.nodes_in_push_order:
        node_idx = state.node_index(node_id)

        inbound_lane_id = tree.inbound_lane_by_node.get(node_id)
        if inbound_lane_id is not None and not (
            disruption_state is not None
            and disruption_state.is_fully_down(element_id=inbound_lane_id, day=current_day)
        ):
            received = shipments.receive(
                lane_id=inbound_lane_id, part_id=sku_id, current_day=current_day
            )
            state.finished_on_hand[node_idx, sku_idx] += received

        outbound = tree.outbound_lanes_by_node.get(node_id, ())
        if not outbound:
            continue

        available = float(state.finished_on_hand[node_idx, sku_idx])
        if available <= 0:
            continue

        backlog_by_lane = {
            lane_id: sum(
                float(state.finished_backlog[state.node_index(customer_id), sku_idx])
                for customer_id in tree.customers_downstream_of_lane.get(lane_id, ())
            )
            for lane_id in outbound
        }
        total_backlog = sum(backlog_by_lane.values())
        ratio_by_lane = (
            {lane_id: 1.0 / len(outbound) for lane_id in outbound}
            if total_backlog <= 0
            else {lane_id: backlog_by_lane[lane_id] / total_backlog for lane_id in outbound}
        )

        for lane_id in outbound:
            if disruption_state is not None and disruption_state.is_fully_down(
                element_id=lane_id, day=current_day
            ):
                continue

            desired = available * ratio_by_lane[lane_id]
            if desired <= 0:
                continue

            lane_shipments = shipments.lanes[lane_id]
            capacity = lane_shipments.capacity_remaining(current_day=current_day)
            if disruption_state is not None:
                capacity *= 1.0 - disruption_state.severity_at(element_id=lane_id, day=current_day)

            shipped = cap_order_quantity(
                desired_quantity=desired, moq=lane_shipments.lane.moq, capacity_remaining=capacity
            )
            if shipped <= 0:
                continue
            if rng is None:
                raise ValueError("rng is required when a distribution push is positive")

            shipments.ship(
                lane_id=lane_id, part_id=sku_id, quantity=shipped, order_day=current_day, rng=rng
            )
            state.finished_on_hand[node_idx, sku_idx] -= shipped
            total_shipped += shipped

    return total_shipped
