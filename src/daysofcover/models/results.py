"""Schema v0: the result envelope.

The engine (Stage 1) is what actually populates ``summary`` and the
per-replication series; this is the container schema so the API (Stage 5)
and the front end (Stage 6) have a stable contract to build against before
the engine exists. Every field the methodology document defines a metric
for gets added here as that metric is implemented, rather than stubbed with
placeholder numbers now.
"""

from __future__ import annotations

from daysofcover.models.network import StrictModel


class ResultSummary(StrictModel):
    """Placeholder for the per-scenario scalar summary row.

    Populated from Stage 3 onward (metrics with bands and half-widths).
    Intentionally near-empty in schema v0: a metrics table guessed at now
    would just be rewritten once docs/explanation/METHODOLOGY.md exists.
    """

    scenario_id: str
    replications_run: int


class Result(StrictModel):
    engine_version: str
    seed: int
    replications: int
    scenario_content_hash: str
    summary: ResultSummary
