"""Schema v0: the network model.

A directed graph of nodes and lanes, plus the parts/SKU/customer layer that
turns it into a supply chain. This is the schema the engine (Stage 1), the
cover and recovery LPs (Stage 2) and the structural screen (Stage 2) all
read. Every duration is in days; every review period is in days; money is
in ``base_currency`` unless a field states its own currency.

Kept deliberately small for Stage 0: enough structure to validate the
seeded Moreton Marine example end to end, with the fields the methodology
document names. Fields the engine does not yet consume (e.g. detailed
policy tuning) are added when the stage that needs them lands, rather than
guessed at now.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_NODES = 100
MAX_LANES = 200
MAX_PARTS = 50


class StrictModel(BaseModel):
    """Base for every schema model: unknown fields are rejected outright.

    Pydantic v2 strict mode plus ``extra="forbid"`` is the project's schema
    validation story (see docs/explanation/ARCHITECTURE.md once it exists,
    and ADR-005 for why recovery is always an input, never a field the
    engine writes back into this layer).
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=False)


class NodeType(StrEnum):
    SUPPLIER = "supplier"
    DISTRIBUTOR = "distributor"
    PORT = "port"
    HUB = "hub"
    WAREHOUSE = "warehouse"
    PLANT = "plant"
    DC = "dc"
    CUSTOMER = "customer"


class LaneMode(StrEnum):
    OCEAN = "ocean"
    AIR = "air"
    ROAD = "road"


class ThreePointDays(StrictModel):
    """A (min, likely, max) estimate in days, fitted with PERT (ADR-005).

    This is always a user-supplied estimate. Nothing in the schema or the
    engine writes a value back into this field — see ADR-005 for why that
    would double-count a quantity the simulation itself produces.
    """

    min_days: float = Field(ge=0)
    likely_days: float = Field(ge=0)
    max_days: float = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> ThreePointDays:
        if not (self.min_days <= self.likely_days <= self.max_days):
            raise ValueError(
                "three-point estimate must satisfy min <= likely <= max "
                f"(got {self.min_days}, {self.likely_days}, {self.max_days})"
            )
        return self


class HazardMembership(StrictModel):
    """One element's membership in a shared-shock hazard group (ADR-001)."""

    hazard_group_id: str
    p_hit: float = Field(ge=0, le=1)


class Node(StrictModel):
    id: str
    name: str
    type: NodeType
    region: str
    capacity_per_week: float | None = Field(default=None, ge=0)
    holding_cost_rate: float | None = Field(default=None, ge=0)
    review_period_days: int | None = Field(default=None, gt=0)
    recovery_days: ThreePointDays | None = None
    hazard_memberships: list[HazardMembership] = Field(default_factory=list)
    idiosyncratic_annual_rate: float | None = Field(default=None, ge=0)
    backlog_window_days: int | None = Field(default=None, ge=0)
    service_threshold: float | None = Field(default=None, ge=0, le=1)


class Reroute(StrictModel):
    target_lane_id: str
    delay_days: float = Field(ge=0)
    cost_premium: float = Field(ge=0)


class Lane(StrictModel):
    id: str
    origin_id: str
    destination_id: str
    mode: LaneMode
    lead_time_days_median: float = Field(gt=0)
    lead_time_days_sigma: float = Field(ge=0)
    capacity_per_week: float = Field(ge=0)
    unit_cost: float = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    reroute: Reroute | None = None
    allow_crossing: bool = False
    recovery_days: ThreePointDays | None = None
    hazard_memberships: list[HazardMembership] = Field(default_factory=list)
    idiosyncratic_annual_rate: float | None = Field(default=None, ge=0)
    moq: float | None = Field(default=None, ge=0)


class SupplySource(StrictModel):
    node_id: str
    split_ratio: float = Field(gt=0, le=1)
    is_primary: bool = True
    detect_delay_days: float = Field(default=0, ge=0)


class Part(StrictModel):
    id: str
    name: str
    suppliers: list[SupplySource] = Field(min_length=1)
    unit_cost: float = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)

    @property
    def single_source(self) -> bool:
        """Derived, not stored: true when exactly one supplier is qualified.

        Matches the plan's "single_source flag derived" note under Part in
        the network-model schema table.
        """
        return len(self.suppliers) == 1

    @model_validator(mode="after")
    def _split_ratios_sum_to_one(self) -> Part:
        total = sum(s.split_ratio for s in self.suppliers)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"part {self.id!r}: supplier split_ratio values must sum to 1.0 (got {total})"
            )
        return self


class BOMLine(StrictModel):
    part_id: str
    quantity: float = Field(gt=0)


class SeasonalDemandProfile(StrictModel):
    """A weekly seasonal profile with negative-binomial noise.

    ``weekly_multipliers`` has 52 entries, one per ISO week, multiplying
    ``base_weekly_rate``. ``dispersion`` is the negative-binomial dispersion
    parameter (smaller = more overdispersed / bursty demand).
    """

    base_weekly_rate: float = Field(ge=0)
    weekly_multipliers: list[float] = Field(min_length=52, max_length=52)
    dispersion: float = Field(gt=0)


class SKU(StrictModel):
    id: str
    name: str
    price: dict[str, float]
    margin_fraction: float = Field(ge=0, le=1)
    currency: str = Field(min_length=3, max_length=3)
    bom: list[BOMLine] = Field(min_length=1)
    production_lead_time_days: float = Field(ge=0)
    batch_size: float = Field(gt=0)


class Customer(StrictModel):
    id: str
    name: str
    demand: dict[str, SeasonalDemandProfile]
    backlog_window_days: int = Field(ge=0)
    allocation_priority: int = Field(ge=0)


class BetaParams(StrictModel):
    alpha: float = Field(gt=0)
    beta: float = Field(gt=0)


class LognormalParams(StrictModel):
    median_days: float = Field(gt=0)
    sigma: float = Field(ge=0)


class HazardGroupMember(StrictModel):
    element_id: str
    p_hit: float = Field(ge=0, le=1)


class HazardGroup(StrictModel):
    id: str
    name: str
    monthly_rate_profile: list[float] = Field(min_length=12, max_length=12)
    severity: BetaParams
    duration: LognormalParams
    members: list[HazardGroupMember] = Field(min_length=1)
    source: str
    notes: str = ""


class Network(StrictModel):
    """The whole network: schema v0.

    ``fx_rates`` maps a foreign currency code to units of ``base_currency``
    per unit of that currency, e.g. ``{"USD": 1.52}`` when base_currency is
    AUD. Cross-referential integrity (lanes/BOM/hazard memberships pointing
    at real ids) and the Stage 0 size caps are enforced below so that a
    malformed or oversized network is rejected before it reaches the engine
    or the API (see the security section of the build plan).
    """

    base_currency: str = Field(min_length=3, max_length=3)
    fx_rates: dict[str, float] = Field(default_factory=dict)
    nodes: list[Node] = Field(min_length=1, max_length=MAX_NODES)
    lanes: list[Lane] = Field(max_length=MAX_LANES)
    parts: list[Part] = Field(max_length=MAX_PARTS)
    skus: list[SKU] = Field(default_factory=list)
    customers: list[Customer] = Field(default_factory=list)
    hazard_groups: list[HazardGroup] = Field(default_factory=list)

    @model_validator(mode="after")
    def _referential_integrity(self) -> Network:
        node_ids = {n.id for n in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise ValueError("duplicate node id")

        lane_ids = {ln.id for ln in self.lanes}
        if len(lane_ids) != len(self.lanes):
            raise ValueError("duplicate lane id")

        for lane in self.lanes:
            if lane.origin_id not in node_ids:
                raise ValueError(
                    f"lane {lane.id!r} origin_id {lane.origin_id!r} is not a known node id"
                )
            if lane.destination_id not in node_ids:
                raise ValueError(
                    f"lane {lane.id!r} destination_id {lane.destination_id!r} "
                    "is not a known node id"
                )
            if lane.reroute is not None and lane.reroute.target_lane_id not in lane_ids:
                raise ValueError(
                    f"lane {lane.id!r} reroute target_lane_id "
                    f"{lane.reroute.target_lane_id!r} is not a known lane id"
                )

        part_ids = {p.id for p in self.parts}
        if len(part_ids) != len(self.parts):
            raise ValueError("duplicate part id")

        for part in self.parts:
            for source in part.suppliers:
                if source.node_id not in node_ids:
                    raise ValueError(
                        f"part {part.id!r} supplier node_id "
                        f"{source.node_id!r} is not a known node id"
                    )

        sku_ids = set()
        for sku in self.skus:
            if sku.id in sku_ids:
                raise ValueError(f"duplicate sku id {sku.id!r}")
            sku_ids.add(sku.id)
            for line in sku.bom:
                if line.part_id not in part_ids:
                    raise ValueError(
                        f"sku {sku.id!r} BOM references unknown part_id {line.part_id!r}"
                    )

        hazard_group_ids = set()
        for group in self.hazard_groups:
            if group.id in hazard_group_ids:
                raise ValueError(f"duplicate hazard_group id {group.id!r}")
            hazard_group_ids.add(group.id)
            for member in group.members:
                if member.element_id not in node_ids and member.element_id not in lane_ids:
                    raise ValueError(
                        f"hazard_group {group.id!r} member "
                        f"{member.element_id!r} is not a known node or lane id"
                    )

        for node in self.nodes:
            for membership in node.hazard_memberships:
                if membership.hazard_group_id not in hazard_group_ids:
                    raise ValueError(
                        f"node {node.id!r} references unknown "
                        f"hazard_group_id {membership.hazard_group_id!r}"
                    )
        for lane in self.lanes:
            for membership in lane.hazard_memberships:
                if membership.hazard_group_id not in hazard_group_ids:
                    raise ValueError(
                        f"lane {lane.id!r} references unknown "
                        f"hazard_group_id {membership.hazard_group_id!r}"
                    )

        return self
