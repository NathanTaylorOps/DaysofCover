"""The multi-node engine's state chassis, indexed by (node, part) and (node, sku).

Session 12 built the first half of this: NumPy arrays indexed by (node,
part) for a purchased component's on-hand, on-order and backlog. This
session adds the second half the daily-step loop needs before it can run
end to end: a *separate* index space for finished goods, matching the
schema's own separation of :class:`daysofcover.models.network.Part` (a
purchased component with suppliers) from
:class:`daysofcover.models.network.SKU` (a produced, sold finished
good) -- a plant's shelf of components and its shelf of finished product
are different things, sized from different lists, and a part id and a
sku id are never the same key space even if a network happened to reuse
a string between them.

Deliberately still deferred: BOM-driven production, the allocation and
split rules, the replication runner with entity-indexed common random
numbers, and warm-up.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from daysofcover.models.network import Network


@dataclass
class NetworkState:
    """Zero-filled state arrays, sized from a real network.

    ``on_hand``, ``on_order`` and ``backlog`` are (node, part) arrays for
    component inventory -- exactly session 12's three arrays. ``finished_
    on_hand`` and ``finished_backlog`` are the (node, sku) equivalents for
    finished-goods inventory: what a plant has actually produced and can
    sell, and how much demand for it is still owed. A node that never
    holds a given part or sku just stays zero there, which costs nothing
    at this network's size.
    """

    node_ids: tuple[str, ...]
    part_ids: tuple[str, ...]
    sku_ids: tuple[str, ...]
    node_index_map: dict[str, int]
    part_index_map: dict[str, int]
    sku_index_map: dict[str, int]
    on_hand: np.ndarray
    on_order: np.ndarray
    backlog: np.ndarray
    finished_on_hand: np.ndarray
    finished_backlog: np.ndarray

    def node_index(self, node_id: str) -> int:
        """This state's row for ``node_id``, or a clear error if it has none."""
        try:
            return self.node_index_map[node_id]
        except KeyError:
            raise KeyError(f"unknown node id {node_id!r}") from None

    def part_index(self, part_id: str) -> int:
        """This state's component column for ``part_id``, or a clear error."""
        try:
            return self.part_index_map[part_id]
        except KeyError:
            raise KeyError(f"unknown part id {part_id!r}") from None

    def sku_index(self, sku_id: str) -> int:
        """This state's finished-goods column for ``sku_id``, or a clear error."""
        try:
            return self.sku_index_map[sku_id]
        except KeyError:
            raise KeyError(f"unknown sku id {sku_id!r}") from None

    @classmethod
    def from_network(cls, network: Network) -> NetworkState:
        """A zero-filled state sized to every node, part and sku in ``network``.

        Row and column order follows ``network.nodes``, ``network.parts``
        and ``network.skus`` exactly, so a state built from the same
        network twice always indexes identically -- the property the
        replication runner's entity-indexed common random numbers will
        depend on once that lands.
        """
        node_ids = tuple(node.id for node in network.nodes)
        part_ids = tuple(part.id for part in network.parts)
        sku_ids = tuple(sku.id for sku in network.skus)
        part_shape = (len(node_ids), len(part_ids))
        sku_shape = (len(node_ids), len(sku_ids))

        return cls(
            node_ids=node_ids,
            part_ids=part_ids,
            sku_ids=sku_ids,
            node_index_map={node_id: i for i, node_id in enumerate(node_ids)},
            part_index_map={part_id: i for i, part_id in enumerate(part_ids)},
            sku_index_map={sku_id: i for i, sku_id in enumerate(sku_ids)},
            on_hand=np.zeros(part_shape),
            on_order=np.zeros(part_shape),
            backlog=np.zeros(part_shape),
            finished_on_hand=np.zeros(sku_shape),
            finished_backlog=np.zeros(sku_shape),
        )
