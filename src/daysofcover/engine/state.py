"""The multi-node engine's state chassis, indexed by (node, part).

Cases 1 to 6, 11, 12 and 13 (sessions 6 to 11) each isolated one mechanic
on a single node or a small serial chain, with its own throwaway state.
The build plan's actual simulation engine, in contrast, holds one shared
state: NumPy arrays indexed by (node, part) for on-hand, on-order and
backlog, plus per-shipment in-transit records generalised across every
lane. This module is that chassis and nothing more -- the daily-step
loop, BOM-driven production, and the allocation and split rules all read
and write through it, but none of them land in this session.

A :class:`NetworkState` is sized from a real :class:`daysofcover.models.
network.Network`: one row per node, one column per part, in the order
those lists were given. ``node_index`` and ``part_index`` translate the
schema's string ids into the array positions the daily-step loop (once
it exists) will actually index into, so nothing downstream ever hard-codes
a row or column number.

Deliberately deferred to later sessions, not forgotten: per-shipment
in-transit records (session 7's per-node heap, generalised to (node,
part)), BOM-driven production, the allocation and split rules, the
replication runner with entity-indexed common random numbers, and warm-up.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from daysofcover.models.network import Network


@dataclass
class NetworkState:
    """Zero-filled (node, part) state arrays, sized from a real network.

    ``on_hand``, ``on_order`` and ``backlog`` are exactly the three
    arrays the build plan names for the engine's state: on-hand
    inventory, quantity already on order but not yet arrived, and
    unmet demand still owed. Every array has shape ``(len(node_ids),
    len(part_ids))``; a node or part that never holds or moves a given
    part just stays zero there, which costs nothing at this network
    size and keeps every downstream rule indexing into the same two
    axes rather than branching on which nodes are relevant.
    """

    node_ids: tuple[str, ...]
    part_ids: tuple[str, ...]
    node_index_map: dict[str, int]
    part_index_map: dict[str, int]
    on_hand: np.ndarray
    on_order: np.ndarray
    backlog: np.ndarray

    def node_index(self, node_id: str) -> int:
        """This state's row for ``node_id``, or a clear error if it has none."""
        try:
            return self.node_index_map[node_id]
        except KeyError:
            raise KeyError(f"unknown node id {node_id!r}") from None

    def part_index(self, part_id: str) -> int:
        """This state's column for ``part_id``, or a clear error if it has none."""
        try:
            return self.part_index_map[part_id]
        except KeyError:
            raise KeyError(f"unknown part id {part_id!r}") from None

    @classmethod
    def from_network(cls, network: Network) -> NetworkState:
        """A zero-filled state sized to every node and part in ``network``.

        Row and column order follows ``network.nodes`` and
        ``network.parts`` exactly, so a state built from the same
        network twice always indexes identically -- the property the
        replication runner's entity-indexed common random numbers will
        depend on once that lands.
        """
        node_ids = tuple(node.id for node in network.nodes)
        part_ids = tuple(part.id for part in network.parts)
        shape = (len(node_ids), len(part_ids))

        return cls(
            node_ids=node_ids,
            part_ids=part_ids,
            node_index_map={node_id: i for i, node_id in enumerate(node_ids)},
            part_index_map={part_id: i for i, part_id in enumerate(part_ids)},
            on_hand=np.zeros(shape),
            on_order=np.zeros(shape),
            backlog=np.zeros(shape),
        )
