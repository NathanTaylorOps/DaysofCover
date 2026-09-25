"""``daysofcover validate`` accepts the shipped example and rejects bad
input, exercised through Typer's CliRunner as the fast/full workflows do.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from daysofcover.cli import app

runner = CliRunner()


def test_validate_accepts_the_shipped_example() -> None:
    result = runner.invoke(app, ["validate"])
    assert result.exit_code == 0
    assert "OK" in result.output


def test_validate_rejects_a_missing_file() -> None:
    result = runner.invoke(app, ["validate", "does-not-exist.json"])
    assert result.exit_code == 1


def test_validate_rejects_malformed_json(tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"base_currency": "AUD", "nodes": [], "lanes": [], "parts": []}))
    # nodes must have at least one entry
    result = runner.invoke(app, ["validate", str(bad)])
    assert result.exit_code == 1
