"""Command-line entry point for Days of Cover."""

import math
from pathlib import Path

import typer

from daysofcover import __version__
from daysofcover.io.loaders import (
    NetworkLoadError,
    StartingInventoryLoadError,
    load_network,
    load_starting_inventory,
)
from daysofcover.lp.aggregate import solve_cover
from daysofcover.lp.structure import structural_convergence

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


@app.command()
def cover(
    path: Path | None = typer.Argument(  # noqa: B008 -- idiomatic Typer usage
        None,
        help="Network JSON file to rank. Defaults to the shipped Moreton Marine example.",
    ),
    state: Path | None = typer.Option(  # noqa: B008 -- idiomatic Typer usage
        None,
        "--state",
        help=(
            "Starting-inventory JSON ({node_id: {'part:<id>'|'sku:<id>': qty}}). "
            "The network schema has no notion of current on-hand stock -- that's "
            "a simulation-runtime fact, not a static network one -- so without "
            "this every node starts at zero, and cover shows as 0 (nothing to "
            "draw down) or unbounded (production alone keeps pace forever)."
        ),
    ),
) -> None:
    """Rank every node and lane by structural convergence and LP cover.

    For each element: the AND/OR structural screen's convergence
    fraction ("structure says") next to the cover LP's own days-of-cover
    ("LP cover") -- the analytical distinction being that these two
    numbers can disagree because structural reachability ignores stock and
    capacity. LP cover is an approximation conditional on starting inventory
    and other assumptions, not a day-by-day simulation. Results are sorted
    by finite LP-estimated cover ascending.
    """
    target = path or DEFAULT_EXAMPLE
    try:
        network = load_network(target)
    except NetworkLoadError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    starting_inventory: dict[tuple[str, tuple[str, str]], float] = {}
    if state is not None:
        try:
            starting_inventory = load_starting_inventory(state)
        except StartingInventoryLoadError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
    else:
        typer.echo(
            "no --state given: every node starts at zero on-hand (see --help for the file format)",
            err=True,
        )

    element_ids = [n.id for n in network.nodes] + [ln.id for ln in network.lanes]
    rows: list[tuple[str, float, float]] = []
    for element_id in element_ids:
        screen = structural_convergence(network, removed_element_id=element_id)
        cover_result = solve_cover(
            network, removed_element_id=element_id, starting_inventory=starting_inventory
        )
        rows.append((element_id, screen.convergence_fraction, cover_result.cover_days))

    def _sort_key(row: tuple[str, float, float]) -> tuple[int, float]:
        cover_days = row[2]
        if math.isnan(cover_days):
            return (2, 0.0)  # solver failure -- rank after everything real
        if math.isinf(cover_days):
            return (1, 0.0)  # unbounded -- rank after every finite cover
        return (0, cover_days)

    rows.sort(key=_sort_key)
    typer.echo(f"{'element':<24}{'structure says':>18}{'LP cover':>20}")
    for element_id, convergence_fraction, cover_days in rows:
        if math.isnan(cover_days):
            cover_text = "error"
        elif math.isinf(cover_days):
            cover_text = "unbounded"
        else:
            cover_text = f"{cover_days:.1f} days"
        typer.echo(f"{element_id:<24}{convergence_fraction:>17.0%}{cover_text:>20}")
