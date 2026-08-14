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


# ------------------------------------------------------------
# P4.0-2: §6.1.4.5 win_rate / recovery_days (requirements v0.4)
# ------------------------------------------------------------


def test_win_rate_counts_positive_months() -> None:
    """win_rate = fraction of months with positive compounded return."""
    # Two months: Jan all-up (positive), Feb all-down (negative).
    jan_days = [date(2024, 1, d) for d in range(1, 32)]
    feb_days = [date(2024, 2, d) for d in range(1, 29)]
    df = pd.DataFrame(
        {
            "trade_date": jan_days + feb_days,
            "daily_return": [0.001] * len(jan_days) + [-0.001] * len(feb_days),
        }
    )

    result = calculate_nav_metrics(df)

    assert "win_rate" in result.metrics
    # 1 positive month out of 2 → 0.5
    assert result.metrics["win_rate"] == pytest.approx(0.5)


def test_recovery_days_measures_trough_to_peak_reclaim() -> None:
    """recovery_days = calendar days from max-drawdown trough to new high."""
    # Flat for 10 days (peak wealth = 1.0), drop 10% on day 11 (trough = 0.9),
    # flat on day 12, then +12% on day 13 reclaims the peak (0.9 * 1.12 = 1.008).
    dates = [date(2024, 1, d) for d in range(1, 31)]
    returns: list[float] = []
    for d in range(1, 31):
        if d == 11:
            returns.append(-0.10)  # drawdown to trough
        elif d == 13:
            returns.append(0.12)   # recovery above pre-drawdown peak
        else:
            returns.append(0.0)    # flat
    df = pd.DataFrame({"trade_date": dates, "daily_return": returns})

    result = calculate_nav_metrics(df)

    assert result.metrics["max_drawdown"] == pytest.approx(-0.10)
    # Trough at 2024-01-11, recovery at 2024-01-13 → 2 calendar days.
    assert result.metrics["recovery_days"] == 2


def test_recovery_days_none_when_drawdown_never_recovers() -> None:
    """recovery_days = None when wealth never reclaims its pre-drawdown peak."""
    # Up 5 days, then steady decline for the rest (never recovers).
    dates = [date(2024, 1, d) for d in range(1, 31)]
    returns = [0.01] * 5 + [-0.01] * 25
    df = pd.DataFrame({"trade_date": dates, "daily_return": returns})

    result = calculate_nav_metrics(df)

    assert result.metrics["max_drawdown"] < 0
    assert result.metrics["recovery_days"] is None


def test_recovery_days_zero_when_no_drawdown() -> None:
    """recovery_days = 0 when the series never draws down."""
    result = calculate_nav_metrics(_nav_frame(30, 0.01))

    assert result.metrics["max_drawdown"] == pytest.approx(0)
    assert result.metrics["recovery_days"] == 0


