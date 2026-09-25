"""Command-line entry point for Days of Cover."""

from pathlib import Path

import typer

from daysofcover import __version__
from daysofcover.io.loaders import NetworkLoadError, load_network

HELP = (
    "Supply chain stress test: how long can you keep shipping if a supplier, "
    "port or route goes down, and what is the cheapest fix."
)

app = typer.Typer(
    name="daysofcover",
    help=HELP,
    add_completion=False,
    no_args_is_help=True,
)

DEFAULT_EXAMPLE = Path(__file__).parent / "data" / "examples" / "moreton_marine" / "network.json"


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"daysofcover {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show the version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """Days of Cover."""


@app.command()
def validate(
    path: Path | None = typer.Argument(  # noqa: B008 -- idiomatic Typer usage
        None,
        help="Network JSON file to validate. Defaults to the shipped Moreton Marine example.",
    ),
) -> None:
    """Validate a network file against the schema and report the result.

    Exits 0 and prints a one-line summary on success; exits 1 and prints
    the schema errors on failure. ``--report`` (generating
    docs/explanation/VALIDATION.md from the test suite) is Stage 1 work,
    once there is an engine whose validation cases have results to report.
    """
    target = path or DEFAULT_EXAMPLE
    try:
        network = load_network(target)
    except NetworkLoadError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(
        f"{target}: OK — {len(network.nodes)} nodes, {len(network.lanes)} lanes, "
        f"{len(network.parts)} parts, {len(network.skus)} SKUs, "
        f"{len(network.customers)} customers, {len(network.hazard_groups)} hazard groups"
    )
