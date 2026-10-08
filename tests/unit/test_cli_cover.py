"""``daysofcover cover`` against the shipped example, exercised through
Typer's CliRunner as the fast/full workflows do (see test_cli_validate.py
for the same pattern on ``validate``).
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from daysofcover.cli import app

runner = CliRunner()


def test_cover_ranks_every_node_and_lane_of_the_shipped_example() -> None:
    result = runner.invoke(app, ["cover"])

    assert result.exit_code == 0
    assert "structure says" in result.output
    assert "aggregate LP" in result.output
    # the shipped example has 33 nodes and 33 lanes -- one ranked row each.
    ranked_rows = (
        result.output.count(" days\n")
        + result.output.count("unbounded\n")
        + result.output.count("error\n")
    )
    assert ranked_rows == 66


def test_cover_warns_when_no_state_file_is_given() -> None:
    result = runner.invoke(app, ["cover"])

    assert "no --state given" in result.output


def test_cover_uses_a_state_file_when_given(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"cust_sydney": {"sku:sku_ais_transponder": 100.0}}))

    result = runner.invoke(app, ["cover", "--state", str(state_path)])

    assert result.exit_code == 0
    assert "no --state given" not in result.output


def test_cover_rejects_a_missing_network_file() -> None:
    result = runner.invoke(app, ["cover", "does-not-exist.json"])
    assert result.exit_code == 1


def test_cover_rejects_a_missing_state_file(tmp_path: Path) -> None:
    result = runner.invoke(app, ["cover", "--state", str(tmp_path / "does-not-exist.json")])
    assert result.exit_code == 1
