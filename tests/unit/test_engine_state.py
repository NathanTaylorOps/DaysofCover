"""Stage 1, sessions 12 and 15: the multi-node state chassis.

Not a validation case: there is no reference number to check here, only
that the chassis the rest of the engine reads and writes through is
sized and indexed correctly, for both index spaces (node, part) and
(node, sku). See :mod:`daysofcover.engine.state` for what it deliberately
does not do yet.
"""

from __future__ import annotations

import numpy as np
import pytest

from daysofcover.engine.state import NetworkState
from daysofcover.models.network import (
    SKU,
    BOMLine,
    Network,
    Node,
    NodeType,
    Part,
    SupplySource,
)


def _tiny_network() -> Network:
    """Two nodes, two parts, one sku -- just enough to size a state."""
    supplier = Node(id="supplier-1", name="Supplier One", type=NodeType.SUPPLIER, region="AU")
    plant = Node(id="plant-1", name="Plant One", type=NodeType.PLANT, region="AU")
    part_a = Part(
        id="part-a",
        name="Part A",
        suppliers=[SupplySource(node_id="supplier-1", split_ratio=1.0)],
        unit_cost=10.0,
        currency="AUD",
    )
    part_b = Part(
        id="part-b",
        name="Part B",
        suppliers=[SupplySource(node_id="supplier-1", split_ratio=1.0)],
        unit_cost=5.0,
        currency="AUD",
    )
    sku_a = SKU(
        id="sku-a",
        name="SKU A",
        price={"AUD": 100.0},
        margin_fraction=0.4,
        currency="AUD",
        bom=[BOMLine(part_id="part-a", quantity=1.0)],
        production_lead_time_days=3.0,
        batch_size=1.0,
    )
    return Network(
        base_currency="AUD",
        nodes=[supplier, plant],
        lanes=[],
        parts=[part_a, part_b],
        skus=[sku_a],
    )


def test_from_network_sizes_arrays_to_nodes_and_parts() -> None:
    state = NetworkState.from_network(_tiny_network())

    assert state.on_hand.shape == (2, 2)
    assert state.on_order.shape == (2, 2)
    assert state.backlog.shape == (2, 2)
    assert np.all(state.on_hand == 0.0)
    assert np.all(state.on_order == 0.0)
    assert np.all(state.backlog == 0.0)


def test_from_network_sizes_finished_goods_arrays_to_nodes_and_skus() -> None:
    state = NetworkState.from_network(_tiny_network())

    assert state.finished_on_hand.shape == (2, 1)
    assert state.finished_backlog.shape == (2, 1)
    assert np.all(state.finished_on_hand == 0.0)
    assert np.all(state.finished_backlog == 0.0)


def test_node_and_part_index_round_trip() -> None:
    state = NetworkState.from_network(_tiny_network())

    assert state.node_index("supplier-1") == 0
    assert state.node_index("plant-1") == 1
    assert state.part_index("part-a") == 0
    assert state.part_index("part-b") == 1


def test_sku_index_round_trip() -> None:
    state = NetworkState.from_network(_tiny_network())

    assert state.sku_index("sku-a") == 0


def test_unknown_id_raises_a_clear_key_error() -> None:
    state = NetworkState.from_network(_tiny_network())

    with pytest.raises(KeyError, match="unknown node id"):
        state.node_index("does-not-exist")

    with pytest.raises(KeyError, match="unknown part id"):
        state.part_index("does-not-exist")

    with pytest.raises(KeyError, match="unknown sku id"):
        state.sku_index("does-not-exist")
