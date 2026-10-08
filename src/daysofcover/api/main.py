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

from fastapi import FastAPI
from pydantic import BaseModel

from daysofcover.io.loaders import load_network
from daysofcover.lp.structure import structural_convergence
from fastapi.staticfiles import StaticFiles

from daysofcover import __version__

if sys.platform != "win32":
    import resource
else:  # pragma: no cover - exercised on the Windows dev machine only
    resource = None

WEB_STATIC_DIR = Path(__file__).resolve().parent.parent / "web_static"

app = FastAPI(title="daysofcover", version=__version__)

EXAMPLE_NETWORK = Path(__file__).resolve().parent.parent / "data" / "examples" / "moreton_marine" / "network.json"


class ExposureRow(BaseModel):
    element_id: str
    element_type: str
    convergence_fraction: float
    affected_customer_sku_pairs: int


class ExposureReport(BaseModel):
    dataset: str
    synthetic: bool
    method: str
    limitations: str
    nodes: int
    lanes: int
    rows: list[ExposureRow]


@app.get("/api/example/exposure", response_model=ExposureReport)
def example_exposure() -> ExposureReport:
    """Structural exposure of the bundled synthetic network; no LP or simulation."""
    network = load_network(EXAMPLE_NETWORK)
    rows: list[ExposureRow] = []
    for element_id, element_type in [
        *((node.id, "node") for node in network.nodes),
        *((lane.id, "lane") for lane in network.lanes),
    ]:
        result = structural_convergence(network, removed_element_id=element_id)
        rows.append(
            ExposureRow(
                element_id=element_id,
                element_type=element_type,
                convergence_fraction=result.convergence_fraction,
                affected_customer_sku_pairs=len(result.cut_pairs),
            )
        )
    rows.sort(key=lambda row: (-row.convergence_fraction, row.element_id))
    return ExposureReport(
        dataset="Moreton Marine Systems",
        synthetic=True,
        method="AND/OR bill-of-materials structural dependency screen",
        limitations="Structural reachability only; excludes inventory, capacity, timing and financial impact.",
        nodes=len(network.nodes),
        lanes=len(network.lanes),
        rows=rows,
    )


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


if WEB_STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEB_STATIC_DIR, html=True), name="web_static")
