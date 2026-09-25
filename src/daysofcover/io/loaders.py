"""Load a Network from JSON with a clean error path.

Kept separate from the CLI so the API (Stage 5) can reuse the same
validation path for uploaded JSON, and so tests can exercise rejection
cases without going through Typer's CliRunner.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from daysofcover.models.network import Network


class NetworkLoadError(Exception):
    """Raised when a network file is missing, malformed JSON, or fails
    schema validation. Wraps the underlying Pydantic ``ValidationError`` (if
    any) so callers get one exception type to catch.
    """


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
