"""Stage 0 API skeleton.

Just enough to satisfy the Stage 0 acceptance criteria: the Docker image
serves a placeholder page with zero toolchain, and the Render skeleton
answers ``/health`` as JSON. This is **not** the Stage 5 API (job runner,
``/runs``, caps, rate limiting, SSE progress) -- that is built once the
engine (Stage 1) exists to actually run something.

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
from fastapi.staticfiles import StaticFiles

from daysofcover import __version__

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


if WEB_STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEB_STATIC_DIR, html=True), name="web_static")
