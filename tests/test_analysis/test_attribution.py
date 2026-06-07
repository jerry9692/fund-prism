"""Static attribution analysis tests."""

from datetime import date

import pandas as pd
import pytest

from fund_research.analysis.attribution import calculate_static_attribution


def test_static_attribution_explains_disclosed_holding_return() -> None:
    """Static attribution should multiply disclosed weights by security period returns."""
    result = calculate_static_attribution(
        pd.DataFrame(
            [
                {
                    "report_date": date(2024, 6, 30),
                    "asset_type": "股票",
                    "security_code": "600519",
                    "security_name": "贵州茅台",
                    "weight_pct": 60.0,
                    "industry": "食品饮料",
                },
                {
                    "report_date": date(2024, 6, 30),
                    "asset_type": "股票",
                    "security_code": "000858",
                    "security_name": "五粮液",
                    "weight_pct": 40.0,
                    "industry": "食品饮料",
                },
            ]
        ),
        pd.DataFrame(
            [
                {
                    "stock_code": "600519",
                    "trade_date": date(2024, 7, 1),
                    "daily_return": 0.10,
                },
                {
                    "stock_code": "000858",
                    "trade_date": date(2024, 7, 1),
                    "daily_return": -0.05,
                },
            ]
        ),
        pd.DataFrame(
            [
                {
                    "trade_date": date(2024, 7, 1),
                    "daily_return": 0.04,
                    "unit_nav": 1.04,
                }
            ]
        ),
    )

    assert result.is_sufficient
    assert result.explained_return == pytest.approx(0.04)
    assert result.total_return == pytest.approx(0.04)
    assert result.residual == pytest.approx(0.0)
    assert result.coverage_rate == 1.0
    assert result.industry_contributions[0]["contribution"] == pytest.approx(0.04)


def test_static_attribution_marks_low_coverage_as_needs_review() -> None:
    """Missing security returns should lower coverage and require review."""
    result = calculate_static_attribution(
        pd.DataFrame(
            [
                {
                    "report_date": date(2024, 3, 31),
                    "asset_type": "股票",
                    "security_code": "600519",
                    "weight_pct": 60.0,
                },
                {
                    "report_date": date(2024, 3, 31),
                    "asset_type": "股票",
                    "security_code": "000858",
                    "weight_pct": 40.0,
                },
            ]
        ),
        pd.DataFrame(
            [
                {
                    "stock_code": "600519",
                    "trade_date": date(2024, 4, 1),
                    "daily_return": 0.10,
                }
            ]
        ),
        pd.DataFrame(
            [
                {
                    "trade_date": date(2024, 4, 1),
                    "daily_return": 0.05,
                }
            ]
        ),
    )

    assert not result.is_sufficient
    assert result.coverage_rate == 0.5
    assert "持仓证券行情覆盖率偏低，静态归因需复核" in result.warnings
    assert "季报通常仅披露前十大重仓，静态归因只能解释披露持仓部分" in result.warnings
