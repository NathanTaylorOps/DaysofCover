"""Hosted preview API and static application entry point.

The Docker image serves the Svelte technical preview and exposes a health
endpoint. Scenario execution, bounded job processing and result reporting
are not yet exposed as HTTP endpoints, even though modelling components
exist in the Python package.

``/health`` is checked before any explicit route registration order
matters here: FastAPI/Starlette matches an exact path before it falls
through to a mount, so defining ``/health`` before mounting the static
files at ``/`` is enough to keep it from being shadowed.

``rss_mb`` on ``/health`` exists only to get a real memory number onto the
free Render tier, which has no metrics dashboard for compute plans below
the paid tiers (confirmed 25 Sep 2026 -- the Metrics page shows an
"upgrade to view application metrics like memory and CPU usage" banner
instead of a graph). ``resource`` is POSIX-only (no such module on
Windows, where this is developed), so it is imported defensively and
``rss_mb`` is ``None`` on a platform without it; the Docker image is
always Linux, so the number that matters is always real.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from daysofcover import __version__
from daysofcover.cli import DEFAULT_EXAMPLE
from daysofcover.io.loaders import load_network
from daysofcover.lp.aggregate import solve_cover
from daysofcover.lp.structure import structural_convergence

if sys.platform != "win32":
    import resource
else:  # pragma: no cover - exercised on the Windows dev machine only
    resource = None

WEB_STATIC_DIR = Path(__file__).resolve().parent.parent / "web_static"

app = FastAPI(title="daysofcover", version=__version__)


def _rss_mb() -> float | None:
    if resource is None:
        return None
    # ru_maxrss is KB on Linux, bytes on macOS; the Docker image only ever
    # runs on the Linux base in the Dockerfile, so KB -> MB is safe here.
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "version": __version__,
        "status": "ok",
        "hosted": True,
        "web_static_present": WEB_STATIC_DIR.is_dir(),
        "rss_mb": _rss_mb(),
    }


@app.get("/api/example/elements")
def example_elements() -> dict[str, object]:
    """List disruption targets in the bundled synthetic example."""
    network = load_network(DEFAULT_EXAMPLE)
    return {
        "dataset": "Moreton Marine Systems (synthetic)",
        "nodes": [{"id": node.id, "name": node.name} for node in network.nodes],
        "lanes": [
            {"id": lane.id, "origin_id": lane.origin_id, "destination_id": lane.destination_id}
            for lane in network.lanes
        ],
    }


@app.get("/api/example/structural-impact/{element_id}")
def example_structural_impact(element_id: str) -> dict[str, object]:
    """Run the structural dependency screen, not a stockout forecast."""
    network = load_network(DEFAULT_EXAMPLE)
    valid_ids = {node.id for node in network.nodes} | {lane.id for lane in network.lanes}
    if element_id not in valid_ids:
        raise HTTPException(status_code=404, detail="Unknown disruption element")
    result = structural_convergence(network, removed_element_id=element_id)
    return {
        "dataset": "Moreton Marine Systems (synthetic)",
        "element_id": element_id,
        "analysis_type": "structural_dependency_screen",
        "convergence_fraction": result.convergence_fraction,
        "interpretation": (
            "Structural dependency exposure only. This is not an inventory, "
            "delivery-timing, financial-loss or time-to-stockout forecast."
        ),
    }


if WEB_STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEB_STATIC_DIR, html=True), name="web_static")
