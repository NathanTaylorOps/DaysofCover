"""Contract tests for the bundled example's structural-exposure API."""

from daysofcover.api.main import example_exposure


def test_example_exposure_returns_ranked_synthetic_network() -> None:
    report = example_exposure()
    assert report.synthetic is True
    assert report.nodes > 0
    assert report.lanes > 0
    assert len(report.rows) == report.nodes + report.lanes
    assert all(0 <= row.convergence_fraction <= 1 for row in report.rows)
    assert all(row.element_type in {"node", "lane"} for row in report.rows)
    assert all(row.affected_customer_sku_pairs >= 0 for row in report.rows)
    assert [row.convergence_fraction for row in report.rows] == sorted(
        (row.convergence_fraction for row in report.rows), reverse=True
    )
    assert "excludes inventory" in report.limitations
