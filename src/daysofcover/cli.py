"""Command-line entry point for Days of Cover."""

import typer

from daysofcover import __version__

app = typer.Typer(
    name="daysofcover",
    help="Supply chain stress test: how long can you keep shipping if a supplier, port or route goes down, and what is the cheapest fix.",
    add_completion=False,
    no_args_is_help=True,
)


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
