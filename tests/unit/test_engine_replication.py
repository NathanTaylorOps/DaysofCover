"""Stage 1: the replication runner with entity-indexed common random numbers.

Session 22's first item off the remaining Engine milestone list. The two
properties that matter -- and the two failure modes that would defeat the
whole point of CRN -- are checked directly: the same entity at the same
replication draws the same numbers across two different calls (even with
a different or reordered entity list), and different entities, or the
same entity at a different replication, do not.
"""

from __future__ import annotations

import numpy as np

from daysofcover.engine.replication import entity_rngs, run_replications


def test_same_entity_same_replication_draws_identically_across_calls() -> None:
    first_call = entity_rngs(entity_ids=["lane-1", "lane-2"], replication=3, seed=42)
    second_call = entity_rngs(entity_ids=["lane-2", "lane-1", "lane-3"], replication=3, seed=42)

    assert np.array_equal(
        first_call["lane-1"].standard_normal(20), second_call["lane-1"].standard_normal(20)
    )


def test_different_entities_in_the_same_call_draw_independently() -> None:
    rngs = entity_rngs(entity_ids=["lane-1", "lane-2"], replication=0, seed=1)
    assert not np.array_equal(
        rngs["lane-1"].standard_normal(10), rngs["lane-2"].standard_normal(10)
    )


def test_same_entity_at_a_different_replication_draws_a_different_stream() -> None:
    first = entity_rngs(entity_ids=["lane-1"], replication=0, seed=1)["lane-1"]
    second = entity_rngs(entity_ids=["lane-1"], replication=1, seed=1)["lane-1"]
    assert not np.array_equal(first.standard_normal(10), second.standard_normal(10))


def test_same_entity_under_a_different_master_seed_draws_a_different_stream() -> None:
    first = entity_rngs(entity_ids=["lane-1"], replication=0, seed=1)["lane-1"]
    second = entity_rngs(entity_ids=["lane-1"], replication=0, seed=2)["lane-1"]
    assert not np.array_equal(first.standard_normal(10), second.standard_normal(10))


def test_run_replications_collects_one_result_per_replication_in_order() -> None:
    def scenario(replication: int, rngs: dict[str, np.random.Generator]) -> tuple[int, float]:
        return (replication, float(rngs["x"].standard_normal()))

    results = run_replications(entity_ids=["x"], n_replications=5, seed=7, scenario=scenario)

    assert [replication for replication, _ in results] == [0, 1, 2, 3, 4]


def test_run_replications_is_deterministic_given_the_same_seed() -> None:
    def scenario(replication: int, rngs: dict[str, np.random.Generator]) -> float:
        return float(rngs["x"].standard_normal())

    first = run_replications(entity_ids=["x"], n_replications=4, seed=99, scenario=scenario)
    second = run_replications(entity_ids=["x"], n_replications=4, seed=99, scenario=scenario)

    assert first == second


def test_run_replications_lets_one_entity_appear_identically_across_two_scenarios() -> None:
    """The point of entity-indexed CRN: a shared entity's draws match across
    two scenario functions with entirely different entity lists, isolating
    whatever the scenarios differ on from random noise."""

    def scenario_a(replication: int, rngs: dict[str, np.random.Generator]) -> float:
        return float(rngs["shared-lane"].standard_normal())

    def scenario_b(replication: int, rngs: dict[str, np.random.Generator]) -> tuple[float, float]:
        shared = float(rngs["shared-lane"].standard_normal())
        other = float(rngs["other-lane"].standard_normal())
        return (shared, other)

    results_a = run_replications(
        entity_ids=["shared-lane"], n_replications=3, seed=5, scenario=scenario_a
    )
    results_b = run_replications(
        entity_ids=["shared-lane", "other-lane"], n_replications=3, seed=5, scenario=scenario_b
    )

    for value_a, (value_b, _) in zip(results_a, results_b, strict=True):
        assert value_a == value_b
