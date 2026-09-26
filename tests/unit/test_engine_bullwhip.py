"""Stage 1, session 9: validation case 11.

The first test in this suite that exercises more than one node: the
demand each node upstream sees is not generated independently, it is the
node below it's own order series. See :mod:`daysofcover.engine.bullwhip`
for the mechanism and why the tolerance here is qualitative rather than a
percentage.
"""

from __future__ import annotations

import pytest

from daysofcover.engine.bullwhip import simulate_bullwhip_chain


@pytest.mark.validation
def test_case_11_bullwhip_variance_amplifies_upstream() -> None:
    """Case 11: Bullwhip.

    Reference: order variance amplifies upstream under (s, S) with
    lead-time lag. Tolerance: qualitative.

    A 3-node chain (customer, retailer, wholesaler, manufacturer) with an
    order-up-to policy driven by a moving-average forecast (the
    demand-signal-processing bullwhip driver -- see the module docstring):
    each node's order variance must exceed the variance of the demand
    signal it itself reacts to, at every stage.
    """
    variances = simulate_bullwhip_chain(
        lam_per_day=10.0,
        n_nodes=3,
        lead_time_days=5,
        forecast_window_days=10,
        n_days=20_000,
        warmup_days=500,
        seed=21,
    )

    assert len(variances) == 4, "customer demand plus 3 nodes' order variances"

    for stage in range(len(variances) - 1):
        assert variances[stage + 1] > variances[stage], (
            f"stage {stage + 1} order variance {variances[stage + 1]:.2f} did not "
            f"exceed stage {stage}'s {variances[stage]:.2f} -- bullwhip should "
            "amplify at every stage, not just the first"
        )
