"""Tests for trading ability three-scenario analysis (requirements v0.4 §6.2.4)."""

from datetime import date, timedelta

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from fund_research.analysis.trading_ability import (
    ALGORITHM_VERSION,
    SCENARIO_DIVERGENCE_THRESHOLD,
    TradingAbilityOutput,
    _compute_three_scenario_trading_returns,
    analyze_trading_ability,
    to_api_data,
)
from fund_research.db.models import FundDisclosedHoldings, FundMain, StockDaily, StockMain

# ============================================================
# Helper: build stock price Series
# ============================================================


def _price_series(prices: list[float], start: date = date(2024, 1, 1)) -> pd.Series:
    """Build a close-price Series with daily dates from a list of prices."""
    dates = [start + timedelta(days=i) for i in range(len(prices))]
    return pd.Series(prices, index=pd.to_datetime(dates), dtype=float)


# ============================================================
# Unit tests: _compute_three_scenario_trading_returns
# ============================================================


class TestThreeScenarioHelper:
    """Test the three-scenario computation without DB."""

    def test_buy_scenarios_correct(self):
        """Buy: entry price unknown → conservative=high, neutral=avg, optimistic=low."""
        # Stock prices in [prev, curr]: low=90, high=110, avg=100, last=105
        prices = _price_series([100, 110, 90, 105])
        prev_date = date(2024, 1, 1)
        curr_date = date(2024, 1, 4)

        result = _compute_three_scenario_trading_returns(
            new_stocks=["001"],
            exited_stocks=[],
            stock_prices={"001": prices},
            prev_date=prev_date,
            curr_date=curr_date,
        )

        # Conservative: (105 - 110) / 110 = -0.04545...
        assert result["conservative"] == pytest.approx(-5.0 / 110.0, abs=1e-6)
        # Neutral: avg = (100+110+90+105)/4 = 101.25 → (105-101.25)/101.25
        avg_price = (100 + 110 + 90 + 105) / 4.0
        assert result["neutral"] == pytest.approx((105 - avg_price) / avg_price, abs=1e-6)
        # Optimistic: (105 - 90) / 90 = 0.16666...
        assert result["optimistic"] == pytest.approx(15.0 / 90.0, abs=1e-6)

    def test_sell_scenarios_correct(self):
        """Sell: exit price unknown → conservative=low, neutral=avg, optimistic=high."""
        # Stock prices in [prev, curr]: first=100, low=95, high=115, avg=105
        prices = _price_series([100, 95, 115, 105])
        prev_date = date(2024, 1, 1)
        curr_date = date(2024, 1, 4)

        result = _compute_three_scenario_trading_returns(
            new_stocks=[],
            exited_stocks=["001"],
            stock_prices={"001": prices},
            prev_date=prev_date,
            curr_date=curr_date,
        )

        # Conservative: (95 - 100) / 100 = -0.05
        assert result["conservative"] == pytest.approx(-0.05, abs=1e-6)
        # Neutral: (105 - 100) / 100 = 0.05  (avg of [100, 95, 115, 105] = 103.75)
        avg_price = (100 + 95 + 115 + 105) / 4.0
        assert result["neutral"] == pytest.approx((avg_price - 100) / 100, abs=1e-6)
        # Optimistic: (115 - 100) / 100 = 0.15
        assert result["optimistic"] == pytest.approx(0.15, abs=1e-6)

    def test_mixed_buy_and_sell_averages_correctly(self):
        """Both buys and sells contribute to the scenario averages."""
        # Buy stock: prices [100, 110, 90, 105] → conservative=-5/110, optimistic=15/90
        # Sell stock: prices [100, 95, 115, 105] → conservative=-5/100, optimistic=15/100
        buy_prices = _price_series([100, 110, 90, 105])
        sell_prices = _price_series([100, 95, 115, 105])
        prev_date = date(2024, 1, 1)
        curr_date = date(2024, 1, 4)

        result = _compute_three_scenario_trading_returns(
            new_stocks=["buy_code"],
            exited_stocks=["sell_code"],
            stock_prices={"buy_code": buy_prices, "sell_code": sell_prices},
            prev_date=prev_date,
            curr_date=curr_date,
        )

        # Average of buy and sell conservative
        buy_cons = -5.0 / 110.0
        sell_cons = -5.0 / 100.0
        assert result["conservative"] == pytest.approx((buy_cons + sell_cons) / 2, abs=1e-6)

        buy_opt = 15.0 / 90.0
        sell_opt = 15.0 / 100.0
        assert result["optimistic"] == pytest.approx((buy_opt + sell_opt) / 2, abs=1e-6)

    def test_empty_stocks_returns_none(self):
        """No trades → all scenarios None."""
        result = _compute_three_scenario_trading_returns(
            new_stocks=[],
            exited_stocks=[],
            stock_prices={},
            prev_date=date(2024, 1, 1),
            curr_date=date(2024, 1, 31),
        )
        assert result["conservative"] is None
        assert result["neutral"] is None
        assert result["optimistic"] is None

    def test_missing_price_data_skipped(self):
        """Stock with no price data in interval is silently skipped."""
        prices = _price_series([100, 110], start=date(2025, 6, 1))  # outside interval
        result = _compute_three_scenario_trading_returns(
            new_stocks=["001"],
            exited_stocks=[],
            stock_prices={"001": prices},
            prev_date=date(2024, 1, 1),
            curr_date=date(2024, 1, 31),
        )
        assert result["conservative"] is None
        assert result["neutral"] is None
        assert result["optimistic"] is None

    def test_flat_prices_produce_equal_scenarios(self):
        """When prices are flat, all three scenarios converge to the same value."""
        prices = _price_series([100, 100, 100, 100])
        result = _compute_three_scenario_trading_returns(
            new_stocks=["001"],
            exited_stocks=[],
            stock_prices={"001": prices},
            prev_date=date(2024, 1, 1),
            curr_date=date(2024, 1, 4),
        )
        # All scenarios = (100 - 100) / 100 = 0.0
        assert result["conservative"] == pytest.approx(0.0, abs=1e-6)
        assert result["neutral"] == pytest.approx(0.0, abs=1e-6)
        assert result["optimistic"] == pytest.approx(0.0, abs=1e-6)


# ============================================================
# Unit tests: to_api_data / output structure
# ============================================================


class TestToApiData:
    """Test API serialization includes three-scenario fields."""

    def test_api_data_includes_three_scenario_fields(self):
        output = TradingAbilityOutput(
            fund_code="000001",
            calc_date=date(2024, 6, 30),
            estimated_trading_return_conservative=-0.05,
            estimated_trading_return_neutral=0.02,
            estimated_trading_return_optimistic=0.15,
            estimated_trading_return_range=0.20,
        )
        data = to_api_data(output)
        assert data["estimated_trading_return_conservative"] == -0.05
        assert data["estimated_trading_return_neutral"] == 0.02
        assert data["estimated_trading_return_optimistic"] == 0.15
        assert data["estimated_trading_return_range"] == 0.20

    def test_api_data_null_scenarios_when_not_computed(self):
        output = TradingAbilityOutput(
            fund_code="000001",
            calc_date=date(2024, 6, 30),
        )
        data = to_api_data(output)
        assert data["estimated_trading_return_conservative"] is None
        assert data["estimated_trading_return_neutral"] is None
        assert data["estimated_trading_return_optimistic"] is None
        assert data["estimated_trading_return_range"] is None

    def test_algorithm_version_bumped(self):
        """Version should be 0.2.0 after adding three-scenario support."""
        assert ALGORITHM_VERSION == "0.2.0"


# ============================================================
# Integration tests: analyze_trading_ability with DB
# ============================================================


def _seed_trading_test_data(
    session: Session,
    fund_code: str = "000001",
    flat_prices: bool = False,
) -> None:
    """Seed DB with 2 report periods of holdings + stock daily prices.

    Period 1 (2024-01-01): holds stock_A, stock_B
    Period 2 (2024-04-01): holds stock_A, stock_C
    - stock_B exited, stock_C is new

    Stock prices in [2024-01-01, 2024-04-01]:
    - stock_B (exited): prev=100, then varies
    - stock_C (new): varies, last=105

    When flat_prices=True, all prices are 100 → scenarios converge → no divergence warning.
    """
    # Parent records for FK
    session.add(FundMain(fund_code=fund_code, short_name="Test Fund", full_name="Test Fund Full"))
    for code in ("000002", "000003", "000004"):
        session.add(StockMain(stock_code=code, stock_name=f"Stock {code}"))

    # Period 1 holdings: stock_A (000002) + stock_B (000003)
    for code in ("000002", "000003"):
        session.add(FundDisclosedHoldings(
            fund_code=fund_code,
            report_date=date(2024, 1, 1),
            asset_type="股票",
            security_code=code,
            security_name=f"Stock {code}",
            weight_pct=50.0,
        ))

    # Period 2 holdings: stock_A (000002) + stock_C (000004)
    for code in ("000002", "000004"):
        session.add(FundDisclosedHoldings(
            fund_code=fund_code,
            report_date=date(2024, 4, 1),
            asset_type="股票",
            security_code=code,
            security_name=f"Stock {code}",
            weight_pct=50.0,
        ))

    # Stock daily prices for the interval [2024-01-01, 2024-04-01]
    # Use ~90 days of data
    if flat_prices:
        # Flat prices → no divergence
        for code in ("000003", "000004"):
            for t in range(90):
                session.add(StockDaily(
                    stock_code=code,
                    trade_date=date(2024, 1, 1) + timedelta(days=t),
                    close_price=100.0,
                    daily_return=0.0,
                ))
    else:
        # stock_B (000003, exited): start at 100, dip to 95, spike to 115, end at 105
        # stock_C (000004, new): start at 100, dip to 90, spike to 110, end at 105
        price_paths = {
            "000003": [100, 95, 115, 105],  # exited stock
            "000004": [100, 90, 110, 105],  # new stock
        }
        for code, prices in price_paths.items():
            # Spread 4 price points across ~90 days, fill rest with last value
            n = 90
            milestones = [0, n // 3, 2 * n // 3, n - 1]
            for t in range(n):
                idx = max(i for i, m in enumerate(milestones) if m <= t)
                session.add(StockDaily(
                    stock_code=code,
                    trade_date=date(2024, 1, 1) + timedelta(days=t),
                    close_price=float(prices[idx]),
                    daily_return=0.0,
                ))

    session.flush()


class TestAnalyzeTradingAbilityIntegration:
    """Integration tests using test_session fixture."""

    def test_three_scenarios_computed_with_diverging_prices(
        self, test_session: Session,
    ):
        """Varying prices → three distinct scenarios + range > threshold → low confidence."""
        _seed_trading_test_data(test_session, flat_prices=False)

        output = analyze_trading_ability(
            db=test_session,
            fund_code="000001",
            evaluation_window_days=30,
        )

        # Three scenarios should be computed and distinct
        assert output.estimated_trading_return_conservative is not None
        assert output.estimated_trading_return_neutral is not None
        assert output.estimated_trading_return_optimistic is not None

        # Conservative < Neutral < Optimistic
        assert output.estimated_trading_return_conservative < output.estimated_trading_return_neutral
        assert output.estimated_trading_return_neutral < output.estimated_trading_return_optimistic

        # Range should exceed threshold → low confidence + warning
        assert output.estimated_trading_return_range > SCENARIO_DIVERGENCE_THRESHOLD
        assert output.confidence == "low"
        assert any("三种假设" in w for w in output.warnings)
        # Still estimated (not needs_review) — scenario divergence is not a data quality issue
        assert output.conclusion_status == "estimated"

    def test_no_divergence_warning_with_flat_prices(
        self, test_session: Session,
    ):
        """Flat prices → scenarios converge → no divergence warning → medium confidence."""
        _seed_trading_test_data(test_session, flat_prices=True)

        output = analyze_trading_ability(
            db=test_session,
            fund_code="000001",
            evaluation_window_days=30,
        )

        # Scenarios should all be ~0 (flat prices)
        assert output.estimated_trading_return_conservative is not None
        assert output.estimated_trading_return_neutral is not None
        assert output.estimated_trading_return_optimistic is not None
        assert output.estimated_trading_return_range == pytest.approx(0.0, abs=1e-6)

        # No divergence warning
        assert not any("三种假设" in w for w in output.warnings)
        # No data quality warnings either (we have price data for all traded stocks)
        assert not any("覆盖率" in w for w in output.warnings)
        # Medium confidence (no warnings at all)
        assert output.confidence == "medium"

    def test_to_api_data_roundtrip_from_full_analysis(
        self, test_session: Session,
    ):
        """to_api_data on a full analysis result includes all new fields."""
        _seed_trading_test_data(test_session, flat_prices=False)

        output = analyze_trading_ability(
            db=test_session,
            fund_code="000001",
            evaluation_window_days=30,
        )
        data = to_api_data(output)

        assert "estimated_trading_return_conservative" in data
        assert "estimated_trading_return_neutral" in data
        assert "estimated_trading_return_optimistic" in data
        assert "estimated_trading_return_range" in data
        assert data["confidence"] == "low"
        assert data["conclusion_status"] == "estimated"
