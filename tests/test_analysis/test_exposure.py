"""Style exposure analysis tests."""

from datetime import date, timedelta

import pandas as pd
import pytest

from fund_research.analysis.exposure import (
    DEFAULT_STYLE_FACTORS,
    MIN_OBSERVATIONS,
    calculate_style_exposure,
)


def _exposure_frames(days: int = 40) -> tuple[pd.DataFrame, pd.DataFrame]:
    start = date(2024, 1, 1)
    fund_rows = []
    factor_rows = []
    for i in range(days):
        trade_date = start + timedelta(days=i)
        large_cap_return = 0.001 * ((i % 5) - 2)
        mid_cap_return = 0.0015 * (((i * 2) % 7) - 3)
        fund_return = 0.6 * large_cap_return + 0.4 * mid_cap_return
        fund_rows.append({"trade_date": trade_date, "daily_return": fund_return})
        factor_rows.extend(
            [
                {
                    "stock_code": DEFAULT_STYLE_FACTORS["large_cap"],
                    "trade_date": trade_date,
                    "daily_return": large_cap_return,
                },
                {
                    "stock_code": DEFAULT_STYLE_FACTORS["mid_cap"],
                    "trade_date": trade_date,
                    "daily_return": mid_cap_return,
                },
            ]
        )
    return pd.DataFrame(fund_rows), pd.DataFrame(factor_rows)


def test_calculate_style_exposure_recovers_latest_window_coefficients() -> None:
    """OLS exposure should recover the linear relationship in the latest window."""
    fund_returns, factor_returns = _exposure_frames()

    result = calculate_style_exposure(fund_returns, factor_returns, window=30)

    assert result.is_sufficient is True
    assert result.observations == 30
    assert result.exposure_values["large_cap"] == pytest.approx(0.6)
    assert result.exposure_values["mid_cap"] == pytest.approx(0.4)
    assert result.r_squared == pytest.approx(1.0)
    assert result.residual == pytest.approx(0.0)
    assert "缺少风格指数行情" in result.warnings[0]


def test_calculate_style_exposure_downgrades_short_input() -> None:
    """Short regression windows should be flagged as needs-review input."""
    fund_returns, factor_returns = _exposure_frames(days=MIN_OBSERVATIONS - 1)

    result = calculate_style_exposure(fund_returns, factor_returns, window=60)

    assert result.is_sufficient is False
    assert result.exposure_values == {}
    assert f"可用回归样本不足 {MIN_OBSERVATIONS} 条，风格暴露需复核" in result.warnings

