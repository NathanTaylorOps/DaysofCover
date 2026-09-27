"""Generate ``VALIDATION.md``: the build plan's own acceptance criterion
for the Stage 1 Engine milestone -- "cases 1 to 6, 11, 12 and 13 pass
with numbers in the generated VALIDATION.md" -- made real.

Every scenario and parameter below is copied from the corresponding
``tests/unit/test_engine_*.py`` case, not re-derived, so the numbers
this script prints are the same numbers the test suite already checks
on every full-workflow run; this script's only job is to run those same
calls once more and lay their result next to each case's published
reference in one document a person can read without opening seven test
files. If a case's own test ever changes its parameters, this script
drifts out of sync with it -- regenerating VALIDATION.md (``python
scripts/generate_validation_report.py``) after any such change is the
fix, not hand-editing the file.

Cases 7 to 10 are not in this list because the build plan's acceptance
criterion does not name them (case 4's own module already covers the
disruption case at case 4; the numbered gaps are the plan's own
numbering, not an omission here). Cases 1, 12 and 13 are exact or
closed-form; 2, 3, 5, 6 and 11 are statistical, each against the same
reference and tolerance its own test uses.
"""

from __future__ import annotations

from pathlib import Path

from daysofcover.engine.bullwhip import simulate_bullwhip_chain
from daysofcover.engine.disruption import simulate_order_pausing_base_stock
from daysofcover.engine.pipeline import lognormal_mean_days, simulate_unit_base_stock_pipeline
from daysofcover.engine.ramp import lost_sales_bounds
from daysofcover.engine.shipment_lag import (
    shipment_recovery_lag_closed_form,
    simulate_shipment_recovery,
)
from daysofcover.engine.single_node import (
    periodic_base_stock_fill_rate_formula,
    simulate_continuous_base_stock,
    simulate_periodic_order_up_to,
    simulate_periodic_s_S,
)

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "VALIDATION.md"


def _case_1() -> str:
    result = simulate_continuous_base_stock(
        daily_demand=10.0, lead_time_days=5, order_up_to=60.0, n_days=30
    )
    return (
        "## Case 1: continuous-review base-stock, deterministic demand\n\n"
        "Reference: exact -- constant demand and a deterministic lead time "
        "leave nothing for a stockout to come from.\n\n"
        f"- Fill rate: {result.fill_rate:.6f} (reference: exactly 1.0)\n"
        f"- Ending on-hand: {result.ending_on_hand:.6f} "
        "(reference: exactly 10.0 = order_up_to 60 - daily_demand 10 * lead_time_days 5)\n"
        f"- **Pass:** {result.fill_rate == 1.0 and result.ending_on_hand == 10.0}\n"
    )


def _case_2() -> str:
    lam, review_period_days, lead_time_days, order_up_to = 5.0, 7, 3, 50
    formula = periodic_base_stock_fill_rate_formula(
        lam_per_day=lam,
        review_period_days=review_period_days,
        lead_time_days=lead_time_days,
        order_up_to=order_up_to,
    )
    simulated = simulate_periodic_order_up_to(
        lam_per_day=lam,
        review_period_days=review_period_days,
        lead_time_days=lead_time_days,
        order_up_to=order_up_to,
        n_reps=2000,
        n_days=200,
        warmup_days=40,
        seed=12345,
    )
    diff = abs(simulated - formula)
    return (
        "## Case 2: periodic-review base-stock (R, S), Poisson demand\n\n"
        "Reference: closed-form fill rate = "
        "1 - [E(D_{R+L} - S)+ - E(D_L - S)+] / E(D_R). Tolerance: 0.02 (absolute).\n\n"
        f"- Formula: {formula:.6f}\n"
        f"- Simulated (2,000 replications): {simulated:.6f}\n"
        f"- Absolute difference: {diff:.6f}\n"
        f"- **Pass:** {diff <= 0.02}\n"
    )


def _case_3() -> str:
    reference_cost = 8.034111561471642
    simulated_cost = simulate_periodic_s_S(
        reorder_point=4.0,
        order_up_to=10.0,
        holding_cost=1.0,
        stockout_cost=4.0,
        fixed_cost=5.0,
        demand_mean=6.0,
        n_days=200_000,
        warmup_days=1000,
        seed=777,
    )
    relative_diff = abs(simulated_cost - reference_cost) / reference_cost
    return (
        "## Case 3: periodic (s, S), discrete Poisson demand\n\n"
        "Reference: stockpyl's published worked example for "
        "`ss.s_s_cost_discrete` (s=4, S=10, holding_cost=1, stockout_cost=4, "
        "fixed_cost=5, Poisson mean 6): 8.034111561471642 per period. "
        "Tolerance: 2% (relative).\n\n"
        f"- Simulated cost per period: {simulated_cost:.6f}\n"
        f"- Reference cost per period: {reference_cost:.6f}\n"
        f"- Relative difference: {relative_diff:.4%}\n"
        f"- **Pass:** {relative_diff <= 0.02}\n"
    )


def _case_4() -> str:
    reference_cost = 2831.9
    simulated_cost = simulate_order_pausing_base_stock(
        daily_demand=2000.0,
        holding_cost=0.25,
        stockout_cost=3.0,
        order_up_to=8000.0,
        disruption_probability=0.04,
        recovery_probability=0.25,
        n_reps=200,
        n_periods=10_000,
        seed=3000,
    )
    relative_diff = abs(simulated_cost - reference_cost) / reference_cost
    return (
        "## Case 4: order-pausing disruptions on a base-stock node\n\n"
        "Reference: stockpyl's `DisruptionProcess` tutorial worked example "
        "(demand 2000/period, holding cost 0.25, stockout cost 3, "
        "base-stock 8000, disruption_probability 0.04, recovery_probability "
        "0.25, zero lead time): 2831.9 per period. Tolerance: 15% (stated, "
        "from a pilot).\n\n"
        f"- Simulated cost per period: {simulated_cost:.2f}\n"
        f"- Reference cost per period: {reference_cost:.2f}\n"
        f"- Relative difference: {relative_diff:.4%}\n"
        f"- **Pass:** {relative_diff <= 0.15}\n"
    )


def _cases_5_and_6() -> str:
    lam_per_day = 2.0
    lead_time_median_days = 10.0
    lead_time_sigma = 0.3
    stats = simulate_unit_base_stock_pipeline(
        lam_per_day=lam_per_day,
        lead_time_median_days=lead_time_median_days,
        lead_time_sigma=lead_time_sigma,
        order_up_to=60,
        n_reps=40,
        n_days=3000,
        warmup_days=300,
        seed=2000,
    )

    palm_target = lam_per_day * lognormal_mean_days(lead_time_median_days, lead_time_sigma)
    palm_diff = abs(stats.mean_outstanding_orders - palm_target) / palm_target

    littles_law_rhs = stats.arrival_rate_per_day * stats.mean_sojourn_days
    littles_diff = abs(stats.mean_pipeline - littles_law_rhs) / stats.mean_pipeline

    return (
        "## Case 5: Palm's theorem on outstanding orders\n\n"
        "Reference: mean outstanding orders = lambda * E[L] under base-stock "
        "with unit Poisson demand and i.i.d. lognormal lead times "
        "(crossing allowed). Tolerance: 2% (relative).\n\n"
        f"- Simulated mean outstanding orders: {stats.mean_outstanding_orders:.4f}\n"
        f"- lambda * E[L]: {palm_target:.4f}\n"
        f"- Relative difference: {palm_diff:.4%}\n"
        f"- **Pass:** {palm_diff <= 0.02}\n\n"
        "## Case 6: Little's law on the shipment pipeline\n\n"
        "Reference: in-transit + on-hand = arrival rate * order-to-receipt "
        "time (an accounting identity, read from the same per-shipment "
        "records as case 5). Tolerance: 1% (relative).\n\n"
        f"- Simulated mean pipeline: {stats.mean_pipeline:.4f}\n"
        f"- arrival_rate * mean_sojourn: {littles_law_rhs:.4f}\n"
        f"- Relative difference: {littles_diff:.4%}\n"
        f"- **Pass:** {littles_diff <= 0.01}\n"
    )


def _case_11() -> str:
    variances = simulate_bullwhip_chain(
        lam_per_day=10.0,
        n_nodes=3,
        lead_time_days=5,
        forecast_window_days=10,
        n_days=20_000,
        warmup_days=500,
        seed=21,
    )
    amplifies_everywhere = all(
        variances[stage + 1] > variances[stage] for stage in range(len(variances) - 1)
    )
    variance_line = " -> ".join(f"{v:.2f}" for v in variances)
    return (
        "## Case 11: bullwhip -- order variance amplifies upstream\n\n"
        "Reference: under (s, S) with a moving-average forecast and "
        "lead-time lag, order variance must exceed the variance of the "
        "demand signal reacted to, at every stage. Tolerance: qualitative.\n\n"
        f"- Order variance by stage (customer demand -> node 1 -> node 2 -> "
        f"node 3): {variance_line}\n"
        f"- **Pass:** {amplifies_everywhere}\n"
    )


def _case_12() -> str:
    daily_demand, downtime_days, ramp_days, n_days = 500.0, 10, 6, 30
    lower, actual, upper = lost_sales_bounds(
        daily_demand=daily_demand, downtime_days=downtime_days, ramp_days=ramp_days, n_days=n_days
    )
    within_bounds = lower < actual < upper
    return (
        "## Case 12: linear production ramp, lost-sales bounds\n\n"
        "Reference: a linear ramp's lost sales sit strictly between the "
        "step-at-restart total (fewest lost sales for this downtime) and "
        "the step-at-(restart + ramp) total (most). Tolerance: exact "
        "closed-form arithmetic.\n\n"
        f"- Lower bound (step at restart): {lower:.2f}\n"
        f"- Actual (linear ramp): {actual:.2f}\n"
        f"- Upper bound (step at restart + ramp): {upper:.2f}\n"
        f"- **Pass:** {within_bounds}\n"
    )


def _case_13() -> str:
    daily_demand, downtime_days, capacity_utilization = 900.0, 2, 0.9
    production_recovery_day, shipment_recovery_day = simulate_shipment_recovery(
        daily_demand=daily_demand,
        downtime_days=downtime_days,
        capacity_utilization=capacity_utilization,
        n_days=200,
    )
    lag_days = shipment_recovery_day - production_recovery_day
    closed_form_lag = shipment_recovery_lag_closed_form(
        downtime_days=downtime_days, capacity_utilization=capacity_utilization
    )
    within_one_day = abs(lag_days - closed_form_lag) <= 1 + 1e-6
    return (
        "## Case 13: shipment-recovery lag behind production recovery\n\n"
        "Reference: at 90% plant utilisation, a short outage leaves a "
        "roughly three-week shipment-recovery lag behind production "
        "recovery (Renesas-shaped). Tolerance: within one day of the "
        "closed form (the discrete/continuous boundary gap).\n\n"
        f"- Production recovery day: {production_recovery_day}\n"
        f"- Shipment recovery day: {shipment_recovery_day}\n"
        f"- Simulated lag: {lag_days} days\n"
        f"- Closed-form lag: {closed_form_lag:.2f} days\n"
        f"- **Pass:** {within_one_day}\n"
    )


def generate() -> str:
    sections = [
        _case_1(),
        _case_2(),
        _case_3(),
        _case_4(),
        _cases_5_and_6(),
        _case_11(),
        _case_12(),
        _case_13(),
    ]
    body = "\n".join(sections)
    return (
        "# Validation\n\n"
        "Generated by `scripts/generate_validation_report.py` -- do not "
        "hand-edit; regenerate it instead. Every case's scenario and "
        "tolerance is copied from its own `tests/unit/test_engine_*.py` "
        "test, not re-derived here; see that test for the reference's "
        "citation. This is the build plan's Stage 1 Engine milestone "
        'acceptance criterion: "cases 1 to 6, 11, 12 and 13 pass with '
        'numbers in the generated VALIDATION.md."\n\n'
        f"{body}"
    )


def main() -> None:
    OUTPUT_PATH.write_text(generate(), encoding="utf-8")
    print(f"wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
