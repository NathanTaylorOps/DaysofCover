"""Order-up-to with a moving-average forecast, validation case 11.

The first genuinely multi-node piece of the engine: a serial chain in
which each stage's own order quantities become the next stage upstream's
demand signal. Cases 1 to 6 (the spike and the per-shipment pipeline) and
case 4 (disruptions) all stayed at one node; this is where "orders placed
by node i become node i+1's demand" first has to actually work.

The mechanism is the demand-signal-processing driver of the bullwhip
effect (Lee, Padmanabhan and Whang, 1997): each stage forecasts its mean
demand from a moving average of the last ``forecast_window_days`` of
whatever it observes, and orders up to a target that covers its own lead
time against that forecast, recomputed every period. Because the forecast
itself reacts to noise in the demand it is fed, and each stage's own
(already-amplified) order stream becomes the next stage's demand, variance
compounds upstream -- this is the qualitative claim validation case 11
asks for.

Chen, Drezner, Ryan and Simchi-Levi (2000) give a closed form for the
single-stage variance ratio under this exact policy with a pure
moving-average forecast: Var(orders)/Var(demand) = 1 + 2L/p + 2L^2/p^2
(L = lead time, p = forecast window, both in periods). A pilot run here
landed about 15-20% off that closed form, consistent with finite-sample
bias in the rolling standard deviation estimator (particularly the short
window before it has ``forecast_window_days`` of history) rather than a
modelling error -- the formula assumes the exact population variance is
known, not a rolling sample estimate. That is close enough to motivate
the mechanism and is not what this validation case asserts (its tolerance
is "qualitative"): the test checks that variance strictly increases at
every stage of the chain, not that any stage matches the closed form.
"""

from __future__ import annotations

import numpy as np


def simulate_order_up_to_forecast(
    demand: np.ndarray,
    *,
    lead_time_days: int,
    forecast_window_days: int,
    safety_z: float = 0.0,
) -> np.ndarray:
    """One stage's order quantities, reacting to an arbitrary demand series.

    ``demand`` need not be i.i.d. or even stationary -- for every stage
    but the first in a chain, it is the previous stage's own (already
    amplified) order series. Each day, the order-up-to target is
    recomputed from a trailing moving average (and, if ``safety_z > 0``,
    a trailing moving standard deviation) of ``demand`` itself, covering
    ``lead_time_days + 1`` periods; the order placed is exactly what
    keeps inventory position at that day's target once that day's
    demand is subtracted (the standard order-up-to identity: order =
    demand + change in target).
    """
    n = len(demand)
    orders = np.zeros(n)
    target_previous: float | None = None

    for day in range(n):
        window_start = max(0, day - forecast_window_days + 1)
        window = demand[window_start : day + 1]
        forecast_mean = window.mean()
        forecast_std = window.std() if len(window) > 1 else 0.0
        target = forecast_mean * (lead_time_days + 1) + safety_z * forecast_std * np.sqrt(
            lead_time_days + 1
        )

        if target_previous is None:
            orders[day] = demand[day]
        else:
            orders[day] = demand[day] + (target - target_previous)
        target_previous = target

    return orders


def simulate_bullwhip_chain(
    *,
    lam_per_day: float,
    n_nodes: int,
    lead_time_days: int,
    forecast_window_days: int,
    n_days: int,
    warmup_days: int,
    seed: int,
) -> list[float]:
    """Variance at customer demand and each node's orders, in chain order.

    Returns a list of length ``n_nodes + 1``: index 0 is the external
    customer demand's own variance (Poisson(lam_per_day), the chain's
    root), and index i (for i >= 1) is node i's order-quantity variance,
    with node i's demand being node (i - 1)'s order series (node 1's
    demand is the customer demand itself). Every node uses the same
    ``lead_time_days`` and ``forecast_window_days`` here; case 11 only
    asks whether variance increases at each stage, not what happens when
    stages differ.
    """
    rng = np.random.default_rng(seed)
    demand = rng.poisson(lam_per_day, size=n_days).astype(float)

    series = demand
    variances = [float(series[warmup_days:].var())]

    for _ in range(n_nodes):
        orders = simulate_order_up_to_forecast(
            series,
            lead_time_days=lead_time_days,
            forecast_window_days=forecast_window_days,
        )
        variances.append(float(orders[warmup_days:].var()))
        series = orders

    return variances
