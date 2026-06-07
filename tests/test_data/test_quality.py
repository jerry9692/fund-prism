"""Data quality check tests."""

from datetime import date

import pandas as pd

from fund_research.data.quality import (
    check_holdings_integrity,
    check_nav_continuity,
    compute_field_coverage,
)


def test_check_nav_continuity_flags_large_daily_return() -> None:
    """NAV quality checks should flag suspicious return jumps and missing fields."""
    report = check_nav_continuity(
        pd.DataFrame(
            [
                {"trade_date": date(2024, 1, 1), "unit_nav": 1.0, "daily_return": 0.01},
                {"trade_date": date(2024, 1, 2), "unit_nav": None, "daily_return": 0.25},
            ]
        )
    )

    assert report.total_records == 2
    assert report.anomaly_count == 1
    assert report.fields_missing == {"unit_nav": 1}
    assert report.coverage_rate == 5 / 6
    assert "日收益异常跳变" in report.warnings[0]


def test_check_holdings_integrity_flags_duplicate_rows() -> None:
    """Holding quality checks should flag exact duplicate disclosed rows."""
    frame = pd.DataFrame(
        [
            {
                "report_date": date(2024, 6, 30),
                "security_code": "600519",
                "weight_pct": 8.5,
            },
            {
                "report_date": date(2024, 6, 30),
                "security_code": "600519",
                "weight_pct": 8.5,
            },
        ]
    )

    report = check_holdings_integrity(frame)

    assert report.anomaly_count == 1
    assert report.checks_failed == 1
    assert "重复记录" in report.warnings[0]


def test_compute_field_coverage_returns_per_column_rates() -> None:
    """Field coverage should be reported per DataFrame column."""
    coverage = compute_field_coverage(pd.DataFrame([{"a": 1, "b": None}, {"a": None, "b": 2}]))

    assert coverage == {"a": 0.5, "b": 0.5}
