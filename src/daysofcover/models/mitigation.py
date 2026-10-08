"""Schema for proposed supply-chain mitigation actions.

The data model defines mitigation categories and cost/capacity inputs.
It does not implement a mitigation-selection optimiser; the corresponding
MILP and decision workflow remain future development.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from daysofcover.models.network import StrictModel


class MitigationKind(StrEnum):
    PRE_QUALIFY_BACKUP = "pre_qualify_backup"
    QUALIFY_ON_DEMAND = "qualify_on_demand"
    STRATEGIC_INVENTORY = "strategic_inventory"
    CONTINGENT_AIR_LANE = "contingent_air_lane"
    FINISHED_GOODS_BUFFER = "finished_goods_buffer"
    SOURCING_SHIFT = "sourcing_shift"


class MitigationOption(StrictModel):
    """One first-stage decision the fixes MILP can choose (ADR terms:
    Tomlin 2006 / Schmitt and Singh pre-qualify vs. qualify-on-demand).
    """

    id: str
    kind: MitigationKind
    target_element_id: str
    one_off_cost: float = Field(ge=0)
    annual_cost: float = Field(ge=0)
    reaction_delay_days: float | None = Field(default=None, ge=0)
    lead_time_days: float | None = Field(default=None, ge=0)
    capacity_per_week: float | None = Field(default=None, ge=0)
