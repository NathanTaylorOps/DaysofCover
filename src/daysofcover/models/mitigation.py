"""Schema v0: fixes-menu options for the Stage 7 optimizer.

Defined now, alongside the rest of schema v0, because ``MitigationOption``
is referenced by the network/scenario layer's documentation and it is
cheap to get the shape right early. The MILP itself (``optimise/menu.py``,
``optimise/milp.py``) is Stage 7 work.
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
