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
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from daysofcover import __version__

WEB_STATIC_DIR = Path(__file__).resolve().parent.parent / "web_static"

app = FastAPI(title="daysofcover", version=__version__)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "version": __version__,
        "status": "ok",
        "hosted": True,
        "web_static_present": WEB_STATIC_DIR.is_dir(),
    }


if WEB_STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEB_STATIC_DIR, html=True), name="web_static")
