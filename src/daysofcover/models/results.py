"""Schema v0: the result envelope.

A minimal result envelope reserved for future end-to-end scenario orchestration.
The engine and LP components exist, but this schema is not yet a complete
contract for scenario execution, reporting or the web interface.
"""

from __future__ import annotations

from daysofcover.models.network import StrictModel


class ResultSummary(StrictModel):
    """Minimal scenario summary identifier and replication count.

    Detailed metrics and uncertainty intervals are not yet defined in this
    public result contract.
    """

    scenario_id: str
    replications_run: int


class Result(StrictModel):
    engine_version: str
    seed: int
    replications: int
    scenario_content_hash: str
    summary: ResultSummary
