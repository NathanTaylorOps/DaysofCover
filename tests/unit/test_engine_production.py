"""Stage 1, session 14: BOM-driven production at a plant.

Not a validation case: three deterministic pieces (feasible units,
component consumption, the fixed-lead-time queue), each checked with
exact arithmetic. See :mod:`daysofcover.engine.production` for what the
plan states in one sentence and this splits into three.
"""

from __future__ import annotations

from daysofcover.engine.production import (
    ProductionQueue,
    consume_components,
    feasible_production_units,
)
from daysofcover.models.network import BOMLine


def test_feasible_production_units_capped_by_capacity() -> None:
    # Components are abundant; only the plant's own daily capacity binds.
    bom = [BOMLine(part_id="part-a", quantity=1.0)]
    on_hand = {"part-a": 10_000.0}

    feasible = feasible_production_units(
        capacity_per_week=700.0,  # 100/day
        on_hand_by_part=on_hand,
        bom=bom,
        batch_size=1.0,
    )

    assert feasible == 100.0


def test_feasible_production_units_capped_by_scarcest_component() -> None:
    # Capacity is generous; part-b only has enough on hand for 30 units.
    bom = [
        BOMLine(part_id="part-a", quantity=1.0),
        BOMLine(part_id="part-b", quantity=2.0),
    ]
    on_hand = {"part-a": 10_000.0, "part-b": 60.0}

    feasible = feasible_production_units(
        capacity_per_week=7_000.0,  # 1000/day
        on_hand_by_part=on_hand,
        bom=bom,
        batch_size=1.0,
    )

    assert feasible == 30.0


def test_feasible_production_units_rounds_down_to_a_whole_batch() -> None:
    bom = [BOMLine(part_id="part-a", quantity=1.0)]
    on_hand = {"part-a": 47.0}

    feasible = feasible_production_units(
        capacity_per_week=7_000.0,
        on_hand_by_part=on_hand,
        bom=bom,
        batch_size=10.0,
    )

    # 47 units are feasible from components alone, but only whole batches
    # of 10 can start, so 40, not 47.
    assert feasible == 40.0


def test_feasible_production_units_treats_a_missing_part_as_zero_on_hand() -> None:
    bom = [BOMLine(part_id="part-a", quantity=1.0), BOMLine(part_id="part-missing", quantity=1.0)]
    on_hand = {"part-a": 500.0}  # part-missing is absent entirely

    feasible = feasible_production_units(
        capacity_per_week=7_000.0,
        on_hand_by_part=on_hand,
        bom=bom,
        batch_size=1.0,
    )

    assert feasible == 0.0


def test_consume_components_decrements_by_bom_quantities_only() -> None:
    bom = [
        BOMLine(part_id="part-a", quantity=1.0),
        BOMLine(part_id="part-b", quantity=3.0),
    ]
    on_hand = {"part-a": 100.0, "part-b": 100.0, "part-unrelated": 100.0}

    updated = consume_components(on_hand_by_part=on_hand, bom=bom, units_produced=10.0)

    assert updated["part-a"] == 90.0
    assert updated["part-b"] == 70.0
    # a part not in the BOM is untouched
    assert updated["part-unrelated"] == 100.0
    # the caller's dict is not mutated
    assert on_hand["part-a"] == 100.0


def test_production_queue_orders_batches_by_ready_day() -> None:
    queue = ProductionQueue()

    first_ready = queue.start(quantity=50.0, start_day=0, lead_time_days=7.0)
    second_ready = queue.start(quantity=30.0, start_day=2, lead_time_days=7.0)

    assert first_ready == 7
    assert second_ready == 9

    assert queue.complete(current_day=6) == 0.0
    assert queue.complete(current_day=7) == 50.0
    assert queue.complete(current_day=8) == 0.0
    assert queue.complete(current_day=9) == 30.0


def test_production_queue_outstanding_before_completion() -> None:
    queue = ProductionQueue()
    queue.start(quantity=50.0, start_day=0, lead_time_days=7.0)
    queue.start(quantity=25.0, start_day=1, lead_time_days=7.0)

    assert queue.outstanding() == 75.0

    queue.complete(current_day=7)
    assert queue.outstanding() == 25.0

    queue.complete(current_day=8)
    assert queue.outstanding() == 0.0
