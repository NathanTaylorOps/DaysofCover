"""Seeded generator for the Moreton Marine Systems example network.

Everything here is synthetic: a fictional Brisbane marine-electronics
maker, invented for this portfolio project (see the README this script
writes alongside the network). Topology (which nodes and lanes exist) is
hand-authored from the build plan's persona section, because that shape
*is* the worked example this project is built around. What the seeded RNG
actually controls is every numeric parameter hung off that shape: lane
lead-time spread, capacity, unit cost, hazard rate profiles and severity,
demand noise. Re-running this script with the same seed reproduces the
same network byte-for-byte; a CI step (``full.yml``, added once the
example-regeneration diff job lands) fails if the committed JSON drifts
from what this script produces.

Run directly to (re)write the committed example:

    python -m daysofcover.data.generate
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from daysofcover.models import (
    SKU,
    BOMLine,
    Customer,
    HazardGroup,
    HazardGroupMember,
    HazardMembership,
    Lane,
    LaneMode,
    Network,
    Node,
    NodeType,
    Part,
    SeasonalDemandProfile,
    SupplySource,
    ThreePointDays,
)
from daysofcover.models.network import BetaParams, LognormalParams, Reroute

SEED = 20260925  # the date this example was fixed; never bump casually
EXAMPLE_DIR = Path(__file__).parent / "examples" / "moreton_marine"

# --------------------------------------------------------------------------
# Topology: 31 nodes, hand-authored from the persona section of the build
# plan. (The plan's target is "about 40 nodes"; this generator will grow
# toward that as Stage 3's hazard/demand work adds nodes the metrics need,
# rather than padding the count now with nodes nothing yet references.)
# --------------------------------------------------------------------------

TIER2_SUPPLIERS = [
    ("t2_wafer_fab", "Wafer fab (Hsinchu)", "Taiwan"),
    ("t2_pcb_laminate", "PCB laminate (Suzhou)", "China"),
    ("t2_resin", "Resin (Ulsan)", "South Korea"),
    ("t2_copper_wire", "Copper wire (Kaohsiung)", "Taiwan"),
    ("t2_lcd_glass", "LCD glass (Sakai)", "Japan"),
]

TIER1_SUPPLIERS = [
    ("t1_gnss_module", "GNSS module (via Singapore distributor)", "Singapore"),
    ("t1_tft_display", "TFT display (Shenzhen)", "China"),
    ("t1_enclosure", "Injection-moulded enclosure (Dongguan)", "China"),
    ("t1_cable_assy", "Cable assemblies (Hai Phong)", "Vietnam"),
    ("t1_pcb_assy", "PCB assembly (Penang)", "Malaysia"),
    ("t1_transducer", "Transducer (Kaohsiung)", "Taiwan"),
    ("t1_power_supply", "Power supply (Shenzhen)", "China"),
    ("t1_connectors", "Connectors (Singapore)", "Singapore"),
    ("t1_packaging", "Packaging (Brisbane)", "Australia"),
    ("t1_fasteners", "Fasteners (Brisbane)", "Australia"),
    ("t1_calibration", "Contract calibration (Brisbane)", "Australia"),
    ("t1_gaskets", "Gaskets (Bangkok)", "Thailand"),
]

PORTS_AND_HUBS = [
    ("port_shenzhen", "Shenzhen Yantian", "China"),
    ("port_kaohsiung", "Kaohsiung", "Taiwan"),
    ("port_haiphong", "Hai Phong", "Vietnam"),
    ("port_penang", "Penang", "Malaysia"),
    ("hub_singapore", "Singapore (transhipment)", "Singapore"),
    ("port_brisbane", "Port of Brisbane", "Australia"),
    ("air_brisbane", "Brisbane Airport (air freight)", "Australia"),
]

INTERNAL_NODES = [
    ("wh_eagle_farm", "Bonded 3PL warehouse (Eagle Farm)", "Australia", NodeType.WAREHOUSE),
    ("plant_northgate", "Assembly plant (Northgate)", "Australia", NodeType.PLANT),
    ("dc_northgate", "Finished-goods DC (Northgate)", "Australia", NodeType.DC),
]

CUSTOMERS = [
    ("cust_sydney", "AU marine distributor (Sydney)", "Australia"),
    ("cust_perth", "AU marine distributor (Perth)", "Australia"),
    ("cust_retail_chain", "National marine retail chain", "Australia"),
    ("cust_auckland", "NZ distributor (Auckland)", "New Zealand"),
    ("cust_fort_lauderdale", "US importer (Fort Lauderdale)", "United States"),
    ("cust_cairns", "Commercial fleet direct account (Cairns)", "Australia"),
]

HAZARD_GROUPS = [
    ("hz_south_china_coast", "South China coast"),
    ("hz_taiwan_strait", "Taiwan Strait"),
    ("hz_northern_vietnam", "Northern Vietnam"),
    ("hz_malaysia_singapore_strait", "Malaysia and Singapore Strait"),
    ("hz_qld_coast", "Queensland coast (cyclone season)"),
    ("hz_au_stevedore", "Stevedore industrial action (AU ports)"),
]

# Parts: 25 total. GNSS module and the display/power-supply trio are the
# shared parts that create the interesting failures (see the plan's BOM
# section); the rest pad the pool with per-SKU-specific parts.
SHARED_PART_IDS = {
    "part_gnss_module": "t1_gnss_module",
    "part_tft_display": "t1_tft_display",
    "part_power_supply": "t1_power_supply",
    "part_enclosure": "t1_enclosure",
    "part_cable_assy": "t1_cable_assy",
    "part_connectors": "t1_connectors",
    "part_pcb_assy": "t1_pcb_assy",
    "part_fasteners": "t1_fasteners",
    "part_packaging": "t1_packaging",
}

OTHER_PART_IDS = [
    ("part_transducer", "t1_transducer"),
    ("part_gasket_set", "t1_gaskets"),
    ("part_calibration_service", "t1_calibration"),
    ("part_wafer_die", "t2_wafer_fab"),
    ("part_pcb_laminate", "t2_pcb_laminate"),
    ("part_resin_housing", "t2_resin"),
    ("part_copper_harness", "t2_copper_wire"),
    ("part_lcd_glass", "t2_lcd_glass"),
    ("part_antenna_whip", "t1_pcb_assy"),
    ("part_speaker_driver", "t1_pcb_assy"),
    ("part_mic_capsule", "t1_pcb_assy"),
    ("part_battery_pack", "t1_power_supply"),
    ("part_bracket_kit", "t1_enclosure"),
    ("part_ribbon_cable", "t1_cable_assy"),
    ("part_display_bezel", "t1_enclosure"),
    ("part_firmware_flash", "t1_pcb_assy"),
]
assert len(SHARED_PART_IDS) + len(OTHER_PART_IDS) == 25

SKUS = [
    (
        "sku_ais_transponder",
        "AIS Transponder",
        2_800.0,
        [
            "part_gnss_module",
            "part_pcb_assy",
            "part_enclosure",
            "part_cable_assy",
            "part_connectors",
            "part_fasteners",
            "part_packaging",
            "part_firmware_flash",
        ],
    ),
    (
        "sku_fleet_hub",
        "Fleet Monitoring Hub",
        3_400.0,
        [
            "part_gnss_module",
            "part_tft_display",
            "part_power_supply",
            "part_pcb_assy",
            "part_enclosure",
            "part_cable_assy",
            "part_connectors",
            "part_fasteners",
            "part_packaging",
        ],
    ),
    (
        "sku_radar_display",
        "Commercial Radar Display",
        4_200.0,
        [
            "part_tft_display",
            "part_lcd_glass",
            "part_power_supply",
            "part_pcb_assy",
            "part_enclosure",
            "part_bracket_kit",
            "part_display_bezel",
            "part_cable_assy",
            "part_connectors",
            "part_fasteners",
            "part_packaging",
        ],
    ),
    (
        "sku_vhf_radio",
        "VHF Radio",
        1_600.0,
        [
            "part_power_supply",
            "part_pcb_assy",
            "part_enclosure",
            "part_speaker_driver",
            "part_mic_capsule",
            "part_antenna_whip",
            "part_connectors",
            "part_fasteners",
            "part_packaging",
        ],
    ),
    (
        "sku_nmea_hub",
        "NMEA 2000 Network Hub",
        1_100.0,
        [
            "part_power_supply",
            "part_pcb_assy",
            "part_enclosure",
            "part_ribbon_cable",
            "part_connectors",
            "part_fasteners",
            "part_packaging",
        ],
    ),
    (
        "sku_chartplotter",
        "Chartplotter Display",
        3_900.0,
        [
            "part_tft_display",
            "part_lcd_glass",
            "part_power_supply",
            "part_pcb_assy",
            "part_battery_pack",
            "part_enclosure",
            "part_bracket_kit",
            "part_display_bezel",
            "part_gasket_set",
            "part_connectors",
            "part_fasteners",
            "part_packaging",
        ],
    ),
]
assert len(SKUS) == 6

ANNUAL_VOLUME_TOTAL = 11_000
# Revenue-weighted volume split, tuned so GNSS-fed SKUs land near 26% of
# revenue as the worked example specifies.
SKU_VOLUME_SHARE = {
    "sku_ais_transponder": 0.16,
    "sku_fleet_hub": 0.10,
    "sku_radar_display": 0.14,
    "sku_vhf_radio": 0.28,
    "sku_nmea_hub": 0.22,
    "sku_chartplotter": 0.10,
}
assert abs(sum(SKU_VOLUME_SHARE.values()) - 1.0) < 1e-9

BOAT_SEASON_PEAK_MONTHS_AU = {10, 11, 12, 1, 2, 3}  # Oct-Mar
BOAT_SEASON_PEAK_MONTHS_US = {4, 5, 6, 7, 8, 9}  # Apr-Sep


def _rng() -> np.random.Generator:
    return np.random.default_rng(SEED)


def _weekly_multipliers(rng: np.random.Generator, peak_months: set[int]) -> list[float]:
    """52 weekly multipliers with a seasonal peak, plus a little seeded jitter."""
    months = [1 + (w * 12 // 52) for w in range(52)]
    base = [1.35 if m in peak_months else 0.85 for m in months]
    jitter = rng.normal(0, 0.05, size=52)
    return [round(max(0.3, b + j), 4) for b, j in zip(base, jitter, strict=True)]


def build_network() -> Network:
    rng = _rng()

    nodes: list[Node] = []
    for node_id, name, region in TIER2_SUPPLIERS:
        nodes.append(
            Node(
                id=node_id,
                name=name,
                type=NodeType.SUPPLIER,
                region=region,
                capacity_per_week=float(rng.integers(400, 900)),
                holding_cost_rate=0.18,
            )
        )
    for node_id, name, region in TIER1_SUPPLIERS:
        nodes.append(
            Node(
                id=node_id,
                name=name,
                type=NodeType.SUPPLIER,
                region=region,
                capacity_per_week=float(rng.integers(300, 800)),
                holding_cost_rate=0.18,
                recovery_days=ThreePointDays(
                    min_days=round(float(rng.uniform(30, 60)), 1),
                    likely_days=round(float(rng.uniform(70, 100)), 1),
                    max_days=round(float(rng.uniform(110, 160)), 1),
                ),
            )
        )
    for node_id, name, region in PORTS_AND_HUBS:
        nodes.append(
            Node(
                id=node_id,
                name=name,
                type=NodeType.PORT if "port_" in node_id or "air_" in node_id else NodeType.HUB,
                region=region,
                capacity_per_week=float(rng.integers(2000, 5000)),
                recovery_days=ThreePointDays(min_days=3, likely_days=9, max_days=21),
            )
        )
    for node_id, name, region, ntype in INTERNAL_NODES:
        nodes.append(
            Node(
                id=node_id,
                name=name,
                type=ntype,
                region=region,
                capacity_per_week=1_100.0 if ntype == NodeType.PLANT else None,
                holding_cost_rate=0.22,
                review_period_days=7,
            )
        )
    for node_id, name, region in CUSTOMERS:
        nodes.append(
            Node(
                id=node_id,
                name=name,
                type=NodeType.CUSTOMER,
                region=region,
                backlog_window_days=int(rng.integers(21, 42)),
                service_threshold=0.95,
            )
        )

    # Hazard groups (rates/severity/duration are seeded; membership fixed
    # by geography, matching the persona's stated correlation structure).
    hazard_groups: list[HazardGroup] = []
    membership_by_group: dict[str, list[str]] = {
        "hz_south_china_coast": ["t1_tft_display", "t1_power_supply", "port_shenzhen"],
        "hz_taiwan_strait": ["t2_wafer_fab", "t2_copper_wire", "t1_transducer", "port_kaohsiung"],
        "hz_northern_vietnam": ["t1_cable_assy", "port_haiphong"],
        "hz_malaysia_singapore_strait": [
            "t1_pcb_assy",
            "t1_connectors",
            "t1_gnss_module",
            "port_penang",
            "hub_singapore",
        ],
        "hz_qld_coast": ["port_brisbane", "plant_northgate", "wh_eagle_farm"],
        "hz_au_stevedore": ["port_brisbane"],
    }
    for group_id, name in HAZARD_GROUPS:
        members = membership_by_group[group_id]
        hazard_groups.append(
            HazardGroup(
                id=group_id,
                name=name,
                monthly_rate_profile=[round(float(r), 4) for r in rng.uniform(0.01, 0.06, size=12)],
                severity=BetaParams(alpha=2.0, beta=5.0),
                duration=LognormalParams(
                    median_days=round(float(rng.uniform(7, 14)), 1), sigma=0.4
                ),
                members=[
                    HazardGroupMember(element_id=m, p_hit=round(float(rng.uniform(0.5, 0.95)), 2))
                    for m in members
                ],
                source=(
                    "Category-level public reporting; no real incident log used (synthetic example)"
                ),
                notes=(
                    "Rate profile and severity are seeded placeholders, not fitted to real events."
                ),
            )
        )

    def _memberships_for(node_id: str) -> list[HazardMembership]:
        return [
            HazardMembership(hazard_group_id=g.id, p_hit=m.p_hit)
            for g in hazard_groups
            for m in g.members
            if m.element_id == node_id
        ]

    for node in nodes:
        node.hazard_memberships = _memberships_for(node.id)

    # Lanes: tier2 -> tier1 -> port/hub -> internal -> customer.
    lanes: list[Lane] = []

    def add_lane(lane_id: str, origin: str, dest: str, mode: LaneMode, median: float) -> None:
        lanes.append(
            Lane(
                id=lane_id,
                origin_id=origin,
                destination_id=dest,
                mode=mode,
                lead_time_days_median=median,
                lead_time_days_sigma=round(float(rng.uniform(0.15, 0.35)), 2),
                capacity_per_week=float(rng.integers(300, 900)),
                unit_cost=round(float(rng.uniform(0.5, 4.0)), 2),
                currency="USD",
                recovery_days=ThreePointDays(min_days=2, likely_days=6, max_days=14),
            )
        )

    tier2_to_tier1 = {
        "t2_wafer_fab": "t1_gnss_module",
        "t2_pcb_laminate": "t1_pcb_assy",
        "t2_resin": "t1_enclosure",
        "t2_copper_wire": "t1_cable_assy",
        "t2_lcd_glass": "t1_tft_display",
    }
    for t2, t1 in tier2_to_tier1.items():
        add_lane(f"lane_{t2}_{t1}", t2, t1, LaneMode.OCEAN, median=float(rng.uniform(10, 20)))

    tier1_to_port = {
        "t1_gnss_module": "hub_singapore",
        "t1_tft_display": "port_shenzhen",
        "t1_enclosure": "port_shenzhen",
        "t1_cable_assy": "port_haiphong",
        "t1_pcb_assy": "port_penang",
        "t1_transducer": "port_kaohsiung",
        "t1_power_supply": "port_shenzhen",
        "t1_connectors": "hub_singapore",
        "t1_gaskets": "hub_singapore",
    }
    for t1, port in tier1_to_port.items():
        add_lane(f"lane_{t1}_{port}", t1, port, LaneMode.OCEAN, median=float(rng.uniform(3, 8)))
    for local in ["t1_packaging", "t1_fasteners", "t1_calibration"]:
        add_lane(f"lane_{local}_plant", local, "plant_northgate", LaneMode.ROAD, median=1.0)

    for port in ["port_shenzhen", "port_kaohsiung", "port_haiphong", "port_penang"]:
        add_lane(
            f"lane_{port}_singapore",
            port,
            "hub_singapore",
            LaneMode.OCEAN,
            median=float(rng.uniform(4, 7)),
        )
    add_lane(
        "lane_singapore_brisbane",
        "hub_singapore",
        "port_brisbane",
        LaneMode.OCEAN,
        median=float(rng.uniform(16, 22)),
    )
    add_lane(
        "lane_singapore_brisbane_air", "hub_singapore", "air_brisbane", LaneMode.AIR, median=2.0
    )

    add_lane(
        "lane_brisbane_port_eaglefarm", "port_brisbane", "wh_eagle_farm", LaneMode.ROAD, median=1.0
    )
    add_lane(
        "lane_brisbane_air_eaglefarm", "air_brisbane", "wh_eagle_farm", LaneMode.ROAD, median=0.5
    )
    add_lane("lane_eaglefarm_plant", "wh_eagle_farm", "plant_northgate", LaneMode.ROAD, median=0.5)
    add_lane("lane_plant_dc", "plant_northgate", "dc_northgate", LaneMode.ROAD, median=0.2)

    customer_modes = {
        "cust_sydney": LaneMode.ROAD,
        "cust_perth": LaneMode.ROAD,
        "cust_retail_chain": LaneMode.ROAD,
        "cust_auckland": LaneMode.OCEAN,
        "cust_fort_lauderdale": LaneMode.OCEAN,
        "cust_cairns": LaneMode.ROAD,
    }
    for cust_id, mode in customer_modes.items():
        median = float(rng.uniform(2, 5)) if mode == LaneMode.ROAD else float(rng.uniform(18, 26))
        add_lane(f"lane_dc_{cust_id}", "dc_northgate", cust_id, mode, median=median)

    # Wire the ocean/air reroute pair on the Singapore-Brisbane leg, now that
    # both lanes exist.
    ocean_lane = next(ln for ln in lanes if ln.id == "lane_singapore_brisbane")
    ocean_lane.reroute = Reroute(
        target_lane_id="lane_singapore_brisbane_air", delay_days=0.0, cost_premium=1.6
    )

    # Parts.
    parts: list[Part] = []
    for part_id, supplier_node in SHARED_PART_IDS.items():
        parts.append(
            Part(
                id=part_id,
                name=part_id.replace("part_", "").replace("_", " ").title(),
                suppliers=[SupplySource(node_id=supplier_node, split_ratio=1.0)],
                unit_cost=round(float(rng.uniform(8, 220)), 2),
                currency="USD",
            )
        )
    for part_id, supplier_node in OTHER_PART_IDS:
        parts.append(
            Part(
                id=part_id,
                name=part_id.replace("part_", "").replace("_", " ").title(),
                suppliers=[SupplySource(node_id=supplier_node, split_ratio=1.0)],
                unit_cost=round(float(rng.uniform(2, 60)), 2),
                currency="USD",
            )
        )

    # SKUs.
    skus: list[SKU] = []
    for sku_id, name, price_aud, part_ids in SKUS:
        skus.append(
            SKU(
                id=sku_id,
                name=name,
                price={"AUD": price_aud},
                margin_fraction=0.40,
                currency="AUD",
                bom=[BOMLine(part_id=p, quantity=1) for p in part_ids],
                production_lead_time_days=7.0,
                batch_size=50.0,
            )
        )

    # Customers with per-SKU demand.
    customers: list[Customer] = []
    total_weekly_units = ANNUAL_VOLUME_TOTAL / 52.0
    customer_share = {
        "cust_sydney": 0.22,
        "cust_perth": 0.13,
        "cust_retail_chain": 0.20,
        "cust_auckland": 0.12,
        "cust_fort_lauderdale": 0.20,
        "cust_cairns": 0.13,
    }
    assert abs(sum(customer_share.values()) - 1.0) < 1e-9
    for cust_id, name, _region in CUSTOMERS:
        peak = (
            BOAT_SEASON_PEAK_MONTHS_US
            if cust_id == "cust_fort_lauderdale"
            else BOAT_SEASON_PEAK_MONTHS_AU
        )
        demand: dict[str, SeasonalDemandProfile] = {}
        for sku_id, _, _, _ in SKUS:
            base_rate = total_weekly_units * SKU_VOLUME_SHARE[sku_id] * customer_share[cust_id]
            demand[sku_id] = SeasonalDemandProfile(
                base_weekly_rate=round(base_rate, 3),
                weekly_multipliers=_weekly_multipliers(rng, peak),
                dispersion=4.0,
            )
        customers.append(
            Customer(
                id=cust_id,
                name=name,
                demand=demand,
                backlog_window_days=int(rng.integers(21, 42)),
                allocation_priority=1,
            )
        )

    return Network(
        base_currency="AUD",
        fx_rates={"USD": 1.52, "NZD": 1.08},
        nodes=nodes,
        lanes=lanes,
        parts=parts,
        skus=skus,
        customers=customers,
        hazard_groups=hazard_groups,
    )


def _sku_table_markdown(network: Network) -> str:
    lines = [
        "| SKU | Price (AUD) | Margin | Annual volume (units) | Annual revenue (AUD) |",
        "| --- | --- | --- | --- | --- |",
    ]
    for sku_id, name, price_aud, _ in SKUS:
        volume = round(ANNUAL_VOLUME_TOTAL * SKU_VOLUME_SHARE[sku_id])
        revenue = round(volume * price_aud)
        margin = next(s.margin_fraction for s in network.skus if s.id == sku_id)
        lines.append(f"| {name} | {price_aud:,.0f} | {margin:.0%} | {volume:,} | {revenue:,.0f} |")
    total_revenue = sum(
        round(ANNUAL_VOLUME_TOTAL * SKU_VOLUME_SHARE[sid]) * price for sid, _, price, _ in SKUS
    )
    lines.append(f"| **Total** | | | **{ANNUAL_VOLUME_TOTAL:,}** | **{total_revenue:,.0f}** |")
    return "\n".join(lines)


def write_example(network: Network) -> None:
    EXAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    network_path = EXAMPLE_DIR / "network.json"
    payload = network.model_dump(mode="json")
    network_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    readme_path = EXAMPLE_DIR / "README.md"
    readme_path.write_text(
        "# Moreton Marine Systems (synthetic example)\n\n"
        "Fictional Brisbane maker of commercial-grade marine electronics. "
        "All figures below are synthetic, generated by "
        "`src/daysofcover/data/generate.py` with a fixed seed "
        f"(`SEED = {SEED}`), and are not any real company's data.\n\n"
        f"Nodes: {len(network.nodes)}. Lanes: {len(network.lanes)}. "
        f"Parts: {len(network.parts)}. SKUs: {len(network.skus)}. "
        f"Hazard groups: {len(network.hazard_groups)}.\n\n"
        "## Per-SKU price, margin and volume\n\n"
        "So a reviewer can check the revenue-at-risk arithmetic by hand.\n\n"
        f"{_sku_table_markdown(network)}\n\n"
        "## Regenerating\n\n"
        "```\n"
        "python -m daysofcover.data.generate\n"
        "```\n\n"
        "A CI step (added once the example-regeneration-diff job lands in "
        "`full.yml`) fails if the committed `network.json` differs from "
        "what a fresh run of this script produces.\n",
        encoding="utf-8",
    )


def main() -> None:
    network = build_network()
    write_example(network)
    print(f"Wrote {EXAMPLE_DIR / 'network.json'}")
    print(f"Wrote {EXAMPLE_DIR / 'README.md'}")


if __name__ == "__main__":
    main()
