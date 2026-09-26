"""Stage 1, sessions 13 and 20: per-lane, per-part in-transit shipments,
capped by MOQ and weekly capacity.

Not a validation case: the point is the bookkeeping, not a reference
number. FIFO enforcement and crossing are tested directly against
:func:`daysofcover.engine.shipments._fifo_arrival_day` and
:meth:`LaneShipments._record_shipment`, with no random draw involved, so
those checks are exact rather than a matter of getting lucky with a
seed; the ship-conservation tests exercise the public, RNG-driven
:meth:`ship` end to end, but only for conservation of quantity, not for
any specific arrival day. Session 20's tests check
:func:`cap_order_quantity` (a pure function, no lane or RNG involved)
and :meth:`LaneShipments.capacity_remaining`'s weekly rollover.
"""

from __future__ import annotations

import numpy as np
import pytest

from daysofcover.engine.shipments import (
    LaneShipments,
    NetworkShipments,
    _fifo_arrival_day,
    cap_order_quantity,
)
from daysofcover.models.network import Lane, LaneMode, Network, Node, NodeType


def _fifo_lane() -> Lane:
    return Lane(
        id="lane-1",
        origin_id="node-a",
        destination_id="node-b",
        mode=LaneMode.OCEAN,
        lead_time_days_median=10.0,
        lead_time_days_sigma=0.3,
        capacity_per_week=1000.0,
        unit_cost=1.0,
        currency="AUD",
        allow_crossing=False,
    )


def _crossing_lane() -> Lane:
    return Lane(
        id="lane-2",
        origin_id="node-a",
        destination_id="node-b",
        mode=LaneMode.AIR,
        lead_time_days_median=3.0,
        lead_time_days_sigma=0.5,
        capacity_per_week=1000.0,
        unit_cost=5.0,
        currency="AUD",
        allow_crossing=True,
    )


def test_fifo_arrival_day_never_arrives_before_the_previous_shipment() -> None:
    assert _fifo_arrival_day(5, None) == 5
    assert _fifo_arrival_day(15, 10) == 15
    # a shorter draw is pushed out to match the shipment ahead of it
    assert _fifo_arrival_day(5, 10) == 10
    assert _fifo_arrival_day(10, 10) == 10


def test_fifo_lane_pushes_out_a_shipment_that_would_overtake_the_one_ahead() -> None:
    shipments = LaneShipments(lane=_fifo_lane())

    first_arrival = shipments._record_shipment(
        part_id="part-a", quantity=100.0, candidate_arrival_day=20
    )
    second_arrival = shipments._record_shipment(
        part_id="part-a", quantity=50.0, candidate_arrival_day=12
    )

    assert first_arrival == 20
    # the second shipment's own draw was earlier, but FIFO holds it back
    assert second_arrival == 20

    # nothing has arrived before day 20, both shipments arrive together on it
    assert shipments.receive(part_id="part-a", current_day=19) == 0.0
    assert shipments.receive(part_id="part-a", current_day=20) == 150.0
    assert shipments.receive(part_id="part-a", current_day=21) == 0.0


def test_crossing_lane_lets_a_later_shipment_arrive_first() -> None:
    shipments = LaneShipments(lane=_crossing_lane())

    shipments._record_shipment(part_id="part-a", quantity=100.0, candidate_arrival_day=20)
    shipments._record_shipment(part_id="part-a", quantity=50.0, candidate_arrival_day=12)

    # the second (later-placed) shipment arrives first -- exactly what a
    # FIFO lane above is not allowed to do
    assert shipments.receive(part_id="part-a", current_day=12) == 50.0
    assert shipments.receive(part_id="part-a", current_day=19) == 0.0
    assert shipments.receive(part_id="part-a", current_day=20) == 100.0


def test_different_parts_on_the_same_lane_do_not_interfere() -> None:
    shipments = LaneShipments(lane=_fifo_lane())

    shipments._record_shipment(part_id="part-a", quantity=100.0, candidate_arrival_day=5)
    shipments._record_shipment(part_id="part-b", quantity=999.0, candidate_arrival_day=5)

    assert shipments.receive(part_id="part-a", current_day=5) == 100.0
    # part-b's shipment is untouched by part-a's receive call
    assert shipments.receive(part_id="part-b", current_day=5) == 999.0


def test_ship_conserves_quantity_through_a_real_random_draw() -> None:
    rng = np.random.default_rng(seed=99)
    shipments = LaneShipments(lane=_fifo_lane())

    total_shipped = 0.0
    for order_day in range(10):
        quantity = 10.0 * (order_day + 1)
        arrival_day = shipments.ship(
            part_id="part-a", quantity=quantity, order_day=order_day, rng=rng
        )
        assert arrival_day >= order_day + 1  # at least a one-day lead time
        total_shipped += quantity

    total_received = shipments.receive(part_id="part-a", current_day=10_000)
    assert total_received == pytest.approx(total_shipped)


def test_network_shipments_indexes_by_lane_id() -> None:
    node_a = Node(id="node-a", name="Node A", type=NodeType.SUPPLIER, region="AU")
    node_b = Node(id="node-b", name="Node B", type=NodeType.PLANT, region="AU")
    network = Network(
        base_currency="AUD",
        nodes=[node_a, node_b],
        lanes=[_fifo_lane(), _crossing_lane()],
        parts=[],
    )
    shipments = NetworkShipments.from_network(network)
    rng = np.random.default_rng(seed=7)

    arrival_day = shipments.ship(
        lane_id="lane-1", part_id="part-a", quantity=42.0, order_day=0, rng=rng
    )
    assert shipments.receive(lane_id="lane-1", part_id="part-a", current_day=arrival_day) == 42.0
    # the other lane's records are untouched
    assert shipments.receive(lane_id="lane-2", part_id="part-a", current_day=arrival_day) == 0.0


def test_cap_order_quantity_passes_through_a_desired_order_with_no_moq() -> None:
    assert cap_order_quantity(desired_quantity=30.0, moq=None, capacity_remaining=1000.0) == 30.0


def test_cap_order_quantity_rounds_a_small_order_up_to_the_moq() -> None:
    assert cap_order_quantity(desired_quantity=20.0, moq=50.0, capacity_remaining=1000.0) == 50.0
    # already above the moq: passes through unchanged
    assert cap_order_quantity(desired_quantity=80.0, moq=50.0, capacity_remaining=1000.0) == 80.0


def test_cap_order_quantity_returns_zero_for_a_non_positive_desired_order() -> None:
    assert cap_order_quantity(desired_quantity=0.0, moq=None, capacity_remaining=1000.0) == 0.0
    assert cap_order_quantity(desired_quantity=-5.0, moq=None, capacity_remaining=1000.0) == 0.0


def test_cap_order_quantity_caps_at_capacity_when_capacity_is_the_binding_limit() -> None:
    # no moq: capacity alone caps the order, no all-or-nothing deferral
    assert cap_order_quantity(desired_quantity=100.0, moq=None, capacity_remaining=40.0) == 40.0


def test_cap_order_quantity_defers_to_zero_when_capacity_cannot_clear_the_moq() -> None:
    # 20 rounds up to the 50-unit moq, but only 30 units of capacity remain
    # this week -- a partial, sub-moq shipment is never placed
    assert cap_order_quantity(desired_quantity=20.0, moq=50.0, capacity_remaining=30.0) == 0.0


def test_capacity_remaining_tracks_usage_within_a_week_and_resets_across_weeks() -> None:
    lane = LaneShipments(lane=_fifo_lane())  # capacity_per_week=1000.0

    assert lane.capacity_remaining(current_day=0) == 1000.0
    rng = np.random.default_rng(seed=1)
    lane.ship(part_id="part-a", quantity=400.0, order_day=0, rng=rng)
    assert lane.capacity_remaining(current_day=3) == 600.0

    lane.ship(part_id="part-a", quantity=600.0, order_day=3, rng=rng)
    assert lane.capacity_remaining(current_day=6) == 0.0

    # day 7 starts a new week (day 6 // 7 == 0, day 7 // 7 == 1): the used-
    # this-week counter resets and the full weekly capacity is back
    assert lane.capacity_remaining(current_day=7) == 1000.0
