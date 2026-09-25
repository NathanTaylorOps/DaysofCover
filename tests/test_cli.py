"""The CLI answers --version with the installed package version."""

from typer.testing import CliRunner

from daysofcover import __version__
from daysofcover.cli import app

runner = CliRunner()


def test_version_flag_prints_package_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"daysofcover {__version__}"


def test_no_arguments_shows_help() -> None:
    result = runner.invoke(app, [])
    assert "Supply chain stress test" in result.output
