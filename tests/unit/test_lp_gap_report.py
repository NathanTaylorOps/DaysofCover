"""``format_gap_finding``'s own edges, separate from case 9's real numbers."""

from __future__ import annotations

import pytest

from daysofcover.lp.gap_report import format_gap_finding


def test_formats_the_build_plans_own_phrasing() -> None:
    result = format_gap_finding(des_cost=3200.0, lp_cost=1600.0)

    assert result == (
        "the simulation's cost exceeds the LP bound by 100%; "
        "that is the price of myopic replenishment"
    )


def test_rejects_a_zero_lp_cost() -> None:
    with pytest.raises(ValueError, match="lp_cost is zero"):
        format_gap_finding(des_cost=500.0, lp_cost=0.0)
