"""Load a Network from JSON with a clean error path.

Kept separate from the CLI so the API (Stage 5) can reuse the same
validation path for uploaded JSON, and so tests can exercise rejection
cases without going through Typer's CliRunner.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from daysofcover.lp.aggregate import CommodityKey, part_key, sku_key
from daysofcover.models.network import Network


class NetworkLoadError(Exception):
    """Raised when a network file is missing, malformed JSON, or fails
    schema validation. Wraps the underlying Pydantic ``ValidationError`` (if
    any) so callers get one exception type to catch.
    """


class StartingInventoryLoadError(Exception):
    """Raised when a ``--state`` file is missing or malformed."""


def load_network(path: str | Path) -> Network:
    """Load and validate a Network from a JSON file.

    Deliberately goes through ``model_validate_json`` on the raw text
    rather than ``json.loads`` followed by ``model_validate``: in strict
    mode (schema v0's whole models are strict), an already-parsed Python
    dict has no way to tell an enum's string value apart from an arbitrary
    string, so ``model_validate`` on Python data rejects exactly the input
    every JSON file produces. Validating the JSON text directly gives
    Pydantic's JSON-mode coercion, which does the right thing for enums,
    and still enforces every other strict-mode rule.
    """
    p = Path(path)
    if not p.is_file():
        raise NetworkLoadError(f"no such file: {p}")
    try:
        return Network.model_validate_json(p.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise NetworkLoadError(f"{p}: schema validation failed:\n{exc}") from exc


def load_starting_inventory(path: str | Path) -> dict[tuple[str, CommodityKey], float]:
    """Load a ``--state`` file for ``daysofcover cover`` (see :mod:`daysofcover.cli`).

    The network schema itself carries no notion of current on-hand
    stock -- that's a simulation-runtime concept, not a static network
    fact -- so ``daysofcover cover`` takes it as a separate file rather
    than trying to derive one. Shape: ``{"<node_id>": {"part:<id>":
    qty, "sku:<id>": qty, ...}, ...}``, the tagged commodity form
    written out as text (see :mod:`daysofcover.lp.aggregate`'s own
    ``part_key``/``sku_key`` for why the tag is needed at all).
    """
    p = Path(path)
    if not p.is_file():
        raise StartingInventoryLoadError(f"no such file: {p}")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StartingInventoryLoadError(f"{p}: malformed JSON: {exc}") from exc

    starting_inventory: dict[tuple[str, CommodityKey], float] = {}
    try:
        for node_id, commodities in raw.items():
            for tagged_id, quantity in commodities.items():
                kind, _, commodity_id = tagged_id.partition(":")
                if kind == "part":
                    key = part_key(commodity_id)
                elif kind == "sku":
                    key = sku_key(commodity_id)
                else:
                    raise StartingInventoryLoadError(
                        f"{p}: {tagged_id!r} must be tagged 'part:<id>' or 'sku:<id>'"
                    )
                starting_inventory[(node_id, key)] = float(quantity)
    except AttributeError as exc:
        raise StartingInventoryLoadError(f"{p}: expected {{node_id: {{tag: quantity}}}}") from exc
    return starting_inventory
