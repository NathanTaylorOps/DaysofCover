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


class DailyOutcome(StrictModel):
    """Observed daily demand, fulfilment and outstanding backlog."""

    day: int
    demand_units: float
    fulfilled_units: float
    backlog_units: float


class RunOutcome(StrictModel):
    """One simulation run with day-level evidence."""

    total_demand_units: float
    total_fulfilled_units: float
    service_fraction: float
    daily: list[DailyOutcome]


class ScenarioComparison(StrictModel):
    """Matched baseline and disruption results with explicit caveats."""

    dataset: str
    synthetic: bool
    element_id: str
    horizon_days: int
    seed: int
    baseline: RunOutcome
    disrupted: RunOutcome
    fulfillment_delta_units: float
    assumptions: list[str]
    limitations: list[str]
