"""NAV metrics tests."""

from datetime import date, timedelta

import pandas as pd
import pytest

from fund_research.analysis.nav_metrics import MIN_OBSERVATIONS, calculate_nav_metrics


def _nav_frame(days: int, daily_return: float) -> pd.DataFrame:
    start = date(2024, 1, 1)
    return pd.DataFrame(
        {
            "trade_date": [start + timedelta(days=i) for i in range(days)],
            "daily_return": [daily_return] * days,
        }
    )


def test_calculate_nav_metrics_from_daily_returns() -> None:
    """Metrics should be computed from decimal daily returns."""
    result = calculate_nav_metrics(_nav_frame(30, 0.01))

    assert result.is_sufficient is True
    assert result.observations == 30
    assert result.metrics["total_return"] == pytest.approx((1.01**30) - 1)
    assert result.metrics["max_drawdown"] == pytest.approx(0)
    assert result.warnings == []


def test_calculate_nav_metrics_downgrades_short_series() -> None:
    """Short return series should remain calculable but flagged for review."""
    result = calculate_nav_metrics(_nav_frame(MIN_OBSERVATIONS - 1, 0.001))

    assert result.is_sufficient is False
    assert result.observations == MIN_OBSERVATIONS - 1
    assert result.warnings == [f"可用收益率样本不足 {MIN_OBSERVATIONS} 条，指标仅供复核"]


def test_calculate_nav_metrics_can_infer_returns_from_nav() -> None:
    """When daily_return is absent, the function should infer returns from NAV."""
    result = calculate_nav_metrics(
        pd.DataFrame(
            {
                "trade_date": [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)],
                "unit_nav": [1.0, 1.1, 1.21],
            }
        )
    )

    assert result.observations == 2
    assert result.metrics["total_return"] == pytest.approx(0.21)
    assert "daily_return 缺失，已使用 unit_nav 推算" in result.warnings

