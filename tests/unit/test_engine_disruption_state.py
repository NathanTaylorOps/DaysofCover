"""Session 22: resolving a scenario's named disruptions against a network.

Not a validation case: :mod:`daysofcover.engine.ramp` already validated
the linear-recovery shape this module reuses (case 12); what's new here
is purely the resolution logic -- which element ids are affected on
which day, and the node-to-lane cascade the build plan itself specifies
("a closed port stops every lane through it"). See
:mod:`daysofcover.engine.disruption_state`'s module docstring for the
full design rationale.
"""

from __future__ import annotations

import pytest

from daysofcover.engine.disruption_state import DisruptionState
from daysofcover.models.network import Lane, LaneMode, Network, Node, NodeType, Part, SupplySource
from daysofcover.models.scenario import Disruption, Scenario


def _three_node_network() -> Network:
    """supplier-1 --lane-1--> port-1 --lane-2--> plant-1, one part."""
    supplier = Node(id="supplier-1", name="Supplier", type=NodeType.SUPPLIER, region="AU")
    port = Node(id="port-1", name="Port", type=NodeType.PORT, region="AU")
    plant = Node(id="plant-1", name="Plant", type=NodeType.PLANT, region="AU")
    lane_1 = Lane(
        id="lane-1",
        origin_id="supplier-1",
        destination_id="port-1",
        mode=LaneMode.OCEAN,
        lead_time_days_median=5.0,
        lead_time_days_sigma=0.0,
        capacity_per_week=1000.0,
        unit_cost=1.0,
        currency="AUD",
    )
    lane_2 = Lane(
        id="lane-2",
        origin_id="port-1",
        destination_id="plant-1",
        mode=LaneMode.ROAD,
        lead_time_days_median=1.0,
        lead_time_days_sigma=0.0,
        capacity_per_week=1000.0,
        unit_cost=1.0,
        currency="AUD",
    )
    part_a = Part(
        id="part-a",
        name="Part A",
        suppliers=[SupplySource(node_id="supplier-1", split_ratio=1.0)],
        unit_cost=1.0,
        currency="AUD",
    )
    return Network(
        base_currency="AUD",
        nodes=[supplier, port, plant],
        lanes=[lane_1, lane_2],
        parts=[part_a],
        skus=[],
    )


def _scenario(*disruptions: Disruption) -> Scenario:
    return Scenario(id="s1", name="Test scenario", disruptions=list(disruptions), seed=1)


def test_no_disruptions_means_zero_severity_everywhere() -> None:
    state = DisruptionState.from_scenario(_scenario(), network=_three_node_network())

    assert state.severity_at(element_id="lane-1", day=0) == 0.0
    assert state.severity_at(element_id="port-1", day=100) == 0.0
    assert not state.is_fully_down(element_id="plant-1", day=0)


def test_lane_disruption_applies_full_severity_during_its_duration() -> None:
    disruption = Disruption(
        element_id="lane-1", start_day=10, severity_fraction=1.0, duration_days=5
    )
    state = DisruptionState.from_scenario(_scenario(disruption), network=_three_node_network())

    assert state.severity_at(element_id="lane-1", day=9) == 0.0
    assert state.severity_at(element_id="lane-1", day=10) == 1.0
    assert state.severity_at(element_id="lane-1", day=14) == 1.0
    # ramp_days defaults to 0: an instant recovery the day after duration ends
    assert state.severity_at(element_id="lane-1", day=15) == 0.0


def test_severity_ramps_down_linearly_after_duration_matching_ramp_py_shape() -> None:
    # severity 1.0, 4-day duration, 4-day ramp -- the exact shape
    # ramp.py's linear_ramp_capacity validates against case 12, just
    # read as severity remaining instead of capacity restored.
    disruption = Disruption(
        element_id="lane-1", start_day=0, severity_fraction=1.0, duration_days=4, ramp_days=4
    )
    state = DisruptionState.from_scenario(_scenario(disruption), network=_three_node_network())

    assert state.severity_at(element_id="lane-1", day=3) == 1.0
    # first day of recovery (day 4): 1 - 1/4 = 0.75
    assert state.severity_at(element_id="lane-1", day=4) == pytest.approx(0.75)
    assert state.severity_at(element_id="lane-1", day=5) == pytest.approx(0.50)
    assert state.severity_at(element_id="lane-1", day=6) == pytest.approx(0.25)
    # last ramp day (day 7): fully recovered
    assert state.severity_at(element_id="lane-1", day=7) == pytest.approx(0.0)
    assert state.severity_at(element_id="lane-1", day=8) == 0.0


def test_partial_severity_fraction_is_a_fractional_slowdown_not_a_closure() -> None:
    disruption = Disruption(
        element_id="lane-1", start_day=0, severity_fraction=0.5, duration_days=10
    )
    state = DisruptionState.from_scenario(_scenario(disruption), network=_three_node_network())

    assert state.severity_at(element_id="lane-1", day=5) == 0.5
    assert not state.is_fully_down(element_id="lane-1", day=5)


def test_node_disruption_cascades_to_every_lane_touching_that_node() -> None:
    # port-1 is lane-1's destination and lane-2's origin -- a closed
    # port stops every lane through it, per the build plan's own words.
    disruption = Disruption(
        element_id="port-1", start_day=0, severity_fraction=1.0, duration_days=10
    )
    state = DisruptionState.from_scenario(_scenario(disruption), network=_three_node_network())

    assert state.severity_at(element_id="port-1", day=0) == 1.0
    assert state.severity_at(element_id="lane-1", day=0) == 1.0
    assert state.severity_at(element_id="lane-2", day=0) == 1.0
    # supplier-1 and plant-1 are not touched by port-1's own disruption
    assert state.severity_at(element_id="supplier-1", day=0) == 0.0
    assert state.severity_at(element_id="plant-1", day=0) == 0.0


def test_lane_disruption_does_not_cascade_back_to_its_endpoint_nodes() -> None:
    # the reverse of the cascade above: disrupting a lane directly
    # never implies its origin or destination node is itself down.
    disruption = Disruption(
        element_id="lane-1", start_day=0, severity_fraction=1.0, duration_days=10
    )
    state = DisruptionState.from_scenario(_scenario(disruption), network=_three_node_network())

    assert state.severity_at(element_id="lane-1", day=0) == 1.0
    assert state.severity_at(element_id="supplier-1", day=0) == 0.0
    assert state.severity_at(element_id="port-1", day=0) == 0.0


def test_two_overlapping_disruptions_on_the_same_element_take_the_worse() -> None:
    mild = Disruption(element_id="lane-1", start_day=0, severity_fraction=0.3, duration_days=20)
    severe = Disruption(element_id="lane-1", start_day=5, severity_fraction=0.9, duration_days=5)
    state = DisruptionState.from_scenario(_scenario(mild, severe), network=_three_node_network())

    # only the mild one is active
    assert state.severity_at(element_id="lane-1", day=2) == pytest.approx(0.3)
    # both active: the severe one wins, not their sum (which would exceed 1.0)
    assert state.severity_at(element_id="lane-1", day=7) == pytest.approx(0.9)


def test_unknown_element_id_raises_a_clear_error() -> None:
    disruption = Disruption(
        element_id="does-not-exist", start_day=0, severity_fraction=1.0, duration_days=5
    )
    with pytest.raises(ValueError, match="not a known node or lane id"):
        DisruptionState.from_scenario(_scenario(disruption), network=_three_node_network())


def test_is_fully_down_is_true_only_at_severity_exactly_one() -> None:
    full = Disruption(element_id="lane-1", start_day=0, severity_fraction=1.0, duration_days=5)
    state = DisruptionState.from_scenario(_scenario(full), network=_three_node_network())

    assert state.is_fully_down(element_id="lane-1", day=2)
    assert not state.is_fully_down(element_id="lane-1", day=10)  # recovered
