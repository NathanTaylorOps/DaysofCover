"""The seeded generator is deterministic and produces a schema-valid
network, per the "Data" section's reproducibility requirement.
"""

from __future__ import annotations

from daysofcover.data.generate import build_network


def test_same_seed_gives_identical_network() -> None:
    first = build_network().model_dump(mode="json")
    second = build_network().model_dump(mode="json")
    assert first == second


def test_generated_network_matches_persona_counts() -> None:
    network = build_network()
    assert len(network.skus) == 6
    assert len(network.customers) == 6
    assert len(network.hazard_groups) == 6
    assert len(network.parts) == 25


def test_gnss_module_is_single_sourced_and_feeds_two_skus() -> None:
    network = build_network()
    gnss = next(p for p in network.parts if p.id == "part_gnss_module")
    assert gnss.single_source

    fed_skus = [sku.id for sku in network.skus if any(bl.part_id == gnss.id for bl in sku.bom)]
    assert set(fed_skus) == {"sku_ais_transponder", "sku_fleet_hub"}
