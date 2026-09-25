"""Schema v0: named scenarios (the sampler override, per ADR-001)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from daysofcover.models.network import StrictModel


class StartWeekPolicy(StrEnum):
    WORST_TIME_OF_YEAR = "worst_time_of_year"
    TYPICAL = "typical"
    FIXED_DATE = "fixed_date"


class Disruption(StrictModel):
    """One named element failure within a scenario."""

    element_id: str
    start_day: int = Field(ge=0)
    severity_fraction: float = Field(gt=0, le=1)
    duration_days: float = Field(gt=0)
    ramp_days: float = Field(default=0, ge=0)


class TariffShock(StrictModel):
    lane_or_customer_id: str
    new_rate: float = Field(ge=0)
    effective_day: int = Field(ge=0)


class FxShock(StrictModel):
    currency: str = Field(min_length=3, max_length=3)
    drift_per_day: float
    volatility_per_day: float = Field(ge=0)
    start_day: int = Field(ge=0)


class Scenario(StrictModel):
    id: str
    name: str
    disruptions: list[Disruption] = Field(default_factory=list)
    tariff_shocks: list[TariffShock] = Field(default_factory=list)
    fx_shocks: list[FxShock] = Field(default_factory=list)
    start_week_policy: StartWeekPolicy = StartWeekPolicy.TYPICAL
    fixed_start_date: str | None = None
    replications: int = Field(default=500, gt=0, le=2000)
    seed: int = Field(ge=0)
    recovery_threshold: float = Field(default=0.95, gt=0, le=1)
    sustain_weeks: int = Field(default=2, gt=0)
