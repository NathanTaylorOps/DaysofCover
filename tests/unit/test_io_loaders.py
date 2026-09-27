"""``load_starting_inventory``, the ``--state`` file loader for ``daysofcover
cover`` -- the network schema itself has no notion of current on-hand
stock, so this is a small, separate JSON format rather than something
derived from the network file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from daysofcover.io.loaders import StartingInventoryLoadError, load_starting_inventory
from daysofcover.lp.aggregate import part_key, sku_key


def test_loads_a_well_formed_state_file(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"n3": {"sku:sku-a": 50.0}, "supplier-1": {"part:part-a": 10.0}}))

    result = load_starting_inventory(path)

    assert result == {
        ("n3", sku_key("sku-a")): 50.0,
        ("supplier-1", part_key("part-a")): 10.0,
    }


def test_rejects_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(StartingInventoryLoadError):
        load_starting_inventory(tmp_path / "does-not-exist.json")


def test_rejects_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not valid json")

    with pytest.raises(StartingInventoryLoadError):
        load_starting_inventory(path)


def test_rejects_an_untagged_commodity_id(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"n3": {"sku-a": 50.0}}))  # missing "sku:" tag

    with pytest.raises(StartingInventoryLoadError):
        load_starting_inventory(path)


def test_rejects_the_wrong_shape(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"n3": 50.0}))  # should be {tag: quantity}, not a bare number

    with pytest.raises(StartingInventoryLoadError):
        load_starting_inventory(path)
