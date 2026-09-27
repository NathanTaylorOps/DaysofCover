"""Validation case 9's own finding, made reusable: "on any network the LP
is an optimistic bound on sales lost plus sales delayed" (the build plan's
own words). The LP's aggregate view has no notion of lead time at all --
it only ever asks whether *total* flow over the whole horizon can match
*total* demand, so a real network's pipeline-fill lag, production ramp
and lot-sizing friction show up in the DES's own numbers but never in the
LP's. This module doesn't compute either side; it only formats the
comparison once a caller has both, so the same wording can be reused by
a later CLI report as well as by the validation test.
"""

from __future__ import annotations


def format_gap_finding(*, des_cost: float, lp_cost: float) -> str:
    """ "the simulation's cost exceeds the LP bound by X%" -- the build plan's own phrasing.

    Raises :class:`ValueError` if ``lp_cost`` is exactly zero -- the LP
    predicting *no* loss at all while the DES loses something is still a
    real, valid finding (an infinite percentage isn't a useful one), so
    that case is a caller's job to word for itself.
    """
    if lp_cost == 0:
        raise ValueError("lp_cost is zero; a percentage-over-zero isn't a meaningful figure")
    gap_fraction = (des_cost - lp_cost) / lp_cost
    return (
        f"the simulation's cost exceeds the LP bound by {gap_fraction:.0%}; "
        "that is the price of myopic replenishment"
    )
