"""Smoke tests for Phase 2 analysis algorithms."""

from datetime import date

import numpy as np
import pandas as pd
import pytest


def _make_random_returns(n_stocks: int = 20, n_days: int = 60) -> np.ndarray:
    rng = np.random.default_rng(42)
    return rng.normal(0.0005, 0.02, (n_stocks, n_days))


def _make_random_fund_returns(n_days: int = 60) -> np.ndarray:
    rng = np.random.default_rng(42)
    return rng.normal(0.0005, 0.015, n_days)


class TestSimulatedHolding:
    """Smoke tests for simulated holding algorithm."""

    def test_import(self):
        from fund_research.analysis.simulated_holding import (
            ALGORITHM_NAME,
        )
        assert ALGORITHM_NAME == "simulated_holding"

    def test_optimize_weights_scipy(self):
        """Basic optimization with scipy fallback works."""
        from fund_research.analysis.simulated_holding import optimize_weights

        ret = _make_random_returns(20, 60)
        f_ret = _make_random_fund_returns(60)
        w, obj = optimize_weights(ret, f_ret, max_positions=5, max_single_weight=0.25, use_cvxpy=False)

        assert len(w) == 20
        assert abs(w.sum() - 1.0) < 0.01
        assert (w >= 0).all()
        assert (w > 0.0001).sum() <= 5

    def test_optimize_weights_cvxpy_respects_max_positions(self):
        """CVXPY path should enforce the requested position limit."""
        from fund_research.analysis import simulated_holding
        from fund_research.analysis.simulated_holding import optimize_weights

        if not simulated_holding._HAS_CVXPY:
            pytest.skip("cvxpy is not installed")

        ret = _make_random_returns(20, 60)
        f_ret = _make_random_fund_returns(60)
        w, _obj = optimize_weights(ret, f_ret, max_positions=5, max_single_weight=0.25, use_cvxpy=True)

        assert abs(w.sum() - 1.0) < 0.01
        assert (w > 0.0001).sum() <= 5

    def test_simulated_holding_api_uses_estimated_fields(self):
        from fund_research.analysis.simulated_holding import SimulatedHoldingResult, SinglePeriodResult

        result = SimulatedHoldingResult(
            fund_code="000001",
            periods=[
                SinglePeriodResult(
                    calc_date=date(2024, 6, 30),
                    holdings=[{"stock_code": "000001", "estimated_weight": 1.0, "confidence": "medium"}],
                    stock_weight_pct=100.0,
                    bond_weight_pct=0.0,
                    cash_weight_pct=0.0,
                    tracking_error=0.01,
                    objective_value=0.0,
                )
            ],
            backtest_report={"top10_recall": 0.8, "industry_correlation": None, "warnings": []},
            overall_tracking_error=0.01,
            overall_top10_recall=0.8,
        )

        data = result.to_api_data()
        assert "estimated_overall_tracking_error" in data
        assert "overall_tracking_error" not in data
        assert "estimated_holdings" in data["periods"][0]
        assert data["conclusion_status"] == "estimated"

    def test_backtest_disclosure_computes_industry_correlation(self):
        from fund_research.analysis.simulated_holding import SinglePeriodResult, backtest_disclosure

        simulated = [
            SinglePeriodResult(
                calc_date=date(2024, 6, 30),
                holdings=[
                    {"stock_code": "000001", "industry": "tech", "estimated_weight": 0.6},
                    {"stock_code": "000002", "industry": "bank", "estimated_weight": 0.4},
                ],
                stock_weight_pct=100.0,
                bond_weight_pct=0.0,
                cash_weight_pct=0.0,
                tracking_error=0.01,
                objective_value=0.0,
            )
        ]
        disclosed = {"2024-06-30": {"000001": 55.0, "000002": 45.0}}
        industries = {"2024-06-30": {"000001": "tech", "000002": "bank"}}

        report = backtest_disclosure(simulated, disclosed, industries)

        assert report["industry_correlation"] is not None
        assert report["detail"][0]["industry_correlation"] is not None

    def test_build_candidate_pool(self):
        from fund_research.analysis.simulated_holding import build_candidate_pool

        stocks = pd.DataFrame({
            "stock_code": [f"{i:06d}" for i in range(50)],
            "industry": ["tech"] * 20 + ["finance"] * 20 + ["health"] * 10,
            "market_cap": np.random.default_rng(42).uniform(10, 1000, 50),
        })
        current = stocks["stock_code"].iloc[:10].tolist()
        pool = build_candidate_pool(current, stocks, max_pool_size=30)
        assert len(pool) <= 30
        assert all(c in pool for c in current[:10])

    def test_run_simulation_empty(self):
        """Empty data returns gracefully with warnings."""
        from fund_research.analysis.simulated_holding import run_simulation

        result = run_simulation(
            "000001",
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
        )
        assert len(result.periods) == 0
        assert result.confidence == "needs_review"


class TestDynamicAttribution:
    """Smoke tests for Brinson attribution."""

    def test_import(self):
        from fund_research.analysis.dynamic_attribution import (
            ALGORITHM_NAME,
        )
        assert ALGORITHM_NAME == "dynamic_attribution"

    def test_single_period_bhb(self):
        from fund_research.analysis.dynamic_attribution import single_period_attribution

        pw = {"tech": 0.5, "finance": 0.3, "health": 0.2}
        bw = {"tech": 0.4, "finance": 0.4, "health": 0.2}
        pr = {"tech": 0.10, "finance": 0.05, "health": 0.02}
        br = {"tech": 0.08, "finance": 0.06, "health": 0.03}

        result = single_period_attribution(pw, bw, pr, br, method="BHB")
        assert result.allocation_effect != 0.0
        assert result.selection_effect != 0.0
        assert len(result.sector_details) == 3

    def test_single_period_bf(self):
        from fund_research.analysis.dynamic_attribution import single_period_attribution

        pw = {"tech": 0.5, "finance": 0.5}
        bw = {"tech": 0.5, "finance": 0.5}
        pr = {"tech": 0.10, "finance": 0.02}
        br = {"tech": 0.10, "finance": 0.02}

        result = single_period_attribution(pw, bw, pr, br, method="BF")
        # Perfect replication: effects should be ~0
        assert abs(result.allocation_effect) < 0.01
        assert abs(result.selection_effect) < 0.01

    def test_run_attribution_empty(self):
        from fund_research.analysis.dynamic_attribution import run_attribution

        result = run_attribution("000001", pd.DataFrame(), pd.DataFrame())
        assert len(result.periods) == 0
        assert result.confidence == "needs_review"

    def test_run_attribution_compounds_multi_period_returns(self):
        from fund_research.analysis.dynamic_attribution import run_attribution

        holdings = pd.DataFrame([
            {"report_date": "2026-01-01", "sector": "A", "port_weight": 1.0, "bench_weight": 1.0},
            {"report_date": "2026-02-01", "sector": "A", "port_weight": 1.0, "bench_weight": 1.0},
        ])
        returns = pd.DataFrame([
            {"report_date": "2026-01-01", "sector": "A", "port_return": 0.10, "bench_return": 0.00},
            {"report_date": "2026-02-01", "sector": "A", "port_return": 0.10, "bench_return": 0.00},
        ])

        result = run_attribution("000001", holdings, returns)

        assert result.total_portfolio_return == pytest.approx(0.21)
        assert abs(result.total_residual) < 1e-3
        assert "estimated_total_portfolio_return" in result.to_api_data()


class TestScoring:
    """Smoke tests for composite scoring."""

    def test_import(self):
        from fund_research.analysis.scoring import (
            ALGORITHM_NAME,
            PRESET_WEIGHTS,
        )
        assert ALGORITHM_NAME == "composite_scoring"
        assert "稳健型" in PRESET_WEIGHTS

    def test_score_funds_preset(self):
        from fund_research.analysis.scoring import score_funds

        rng = np.random.default_rng(42)
        n = 30
        data = pd.DataFrame({
            "fund_code": [f"{i:06d}" for i in range(n)],
            "return": rng.normal(0.10, 0.15, n),
            "risk": -rng.uniform(0.05, 0.25, n),  # negative = lower is better, need to pre-orient
            "alpha": rng.normal(0.02, 0.08, n),
            "trading": rng.normal(0.01, 0.05, n),
            "style_stability": rng.uniform(0.3, 1.0, n),
            "scale": rng.uniform(0.2, 1.0, n),
            "team": rng.uniform(0.5, 1.0, n),
            "holder": rng.uniform(0.0, 1.0, n),
        })

        result = score_funds(data, preset="均衡型", category="混合型-偏股")
        assert result.fund_count == 30
        assert len(result.fund_scores) == 30
        # Scores should be 0-100 and sorted
        scores = [fs.total_score for fs in result.fund_scores]
        assert all(0 <= s <= 100 for s in scores)
        assert scores == sorted(scores, reverse=True)

    def test_score_funds_with_estimated(self):
        from fund_research.analysis.scoring import score_funds

        data = pd.DataFrame({
            "fund_code": ["000001"],
            "return": [0.12], "risk": [0.10], "alpha": [0.03],
            "trading": [0.01], "style_stability": [0.8],
            "scale": [0.7], "team": [0.9], "holder": [0.6],
        })
        result = score_funds(data, contains_estimated={"trading"})
        assert result.fund_scores[0].contains_estimated
        assert any("trading" in r and "估计" in r for r in result.fund_scores[0].deduction_reasons)

    def test_score_funds_does_not_penalize_unknown_sample_years(self):
        from fund_research.analysis.scoring import score_funds

        data = pd.DataFrame({
            "fund_code": ["000001", "000002"],
            "return": [0.12, 0.08],
            "risk": [0.10, 0.12],
        })

        result = score_funds(data, weights={"return": 0.5, "risk": 0.5})

        assert all("样本期仅" not in " ".join(fs.deduction_reasons) for fs in result.fund_scores)
        assert all(fs.sample_years is None for fs in result.fund_scores)

    def test_score_funds_applies_material_missing_data_penalty(self):
        from fund_research.analysis.scoring import score_funds

        data = pd.DataFrame({
            "fund_code": ["A", "B"],
            "return": [0.2, None],
            "risk": [0.2, 0.1],
        })

        result = score_funds(data, weights={"return": 0.5, "risk": 0.5}, sample_years_map={"A": 5, "B": 5})
        by_code = {fs.fund_code: fs for fs in result.fund_scores}

        assert "return 数据缺失" in by_code["B"].deduction_reasons
        assert by_code["B"].total_score <= 50 - 2.5

    def test_compute_scoring_backtest_groups_future_returns(self):
        from fund_research.analysis.scoring import compute_scoring_backtest

        scores = pd.DataFrame({
            "fund_code": [f"{i:06d}" for i in range(6)],
            "calc_date": [date(2024, 6, 30)] * 6,
            "score": [10, 20, 30, 40, 50, 60],
        })
        future_returns = pd.DataFrame({
            "fund_code": [f"{i:06d}" for i in range(6)],
            "calc_date": [date(2024, 6, 30)] * 6,
            "future_return": [-0.03, -0.01, 0.0, 0.02, 0.04, 0.06],
            "future_max_drawdown": [-0.12, -0.10, -0.08, -0.06, -0.04, -0.02],
            "future_sharpe": [-0.5, -0.2, 0.0, 0.4, 0.8, 1.2],
        })

        result = compute_scoring_backtest(scores, future_returns, group_count=3)

        assert result["sample_count"] == 6
        assert result["ic_mean"] == 1.0
        assert result["monotonicity"] is True
        assert len(result["group_returns"]) == 3
        assert result["group_results"]["2"]["future_sharpe"] > result["group_results"]["0"]["future_sharpe"]
        assert result["monotonicity_by_metric"]["future_max_drawdown"] is True
        assert result["top_bottom_return_spread"] > 0
        assert result["top_bottom_one_sided_p_value"] == 0.5

    def test_compute_ic_random(self):
        """Random scores show near-zero IC."""
        from fund_research.analysis.scoring import compute_ic

        rng = np.random.default_rng(42)
        n_funds = 30
        n_dates = 4
        rows = []
        for d in range(n_dates):
            for f in range(n_funds):
                rows.append({
                    "fund_code": f"{f:06d}",
                    "calc_date": date(2024, (d * 3 + 3), 30),
                    "score": rng.uniform(0, 100),
                })
        scores = pd.DataFrame(rows)
        future = pd.DataFrame([
            {"fund_code": row["fund_code"], "calc_date": row["calc_date"],
             "future_return": rng.normal(0, 0.05)}
            for _, row in scores.iterrows()
        ])
        result = compute_ic(scores, future)
        assert result["ic_count"] == n_dates
        assert result["ic_mean"] is not None
        assert abs(result["ic_mean"]) < 0.5  # random → low IC

    def test_compute_ic_perfect_predictor(self):
        """Perfect monotonic scores → positive IC and monotonicity."""
        from fund_research.analysis.scoring import compute_ic

        rng = np.random.default_rng(99)
        n_funds = 20
        rows = []
        for d in range(3):
            # Create scores that perfectly rank future returns
            base_returns = rng.normal(0.05, 0.10, n_funds)
            for f in range(n_funds):
                rows.append({
                    "fund_code": f"{f:06d}",
                    "calc_date": date(2024, (d * 3 + 3), 30),
                    "score": float(base_returns[f]),
                })
        scores = pd.DataFrame(rows)
        future = pd.DataFrame([
            {"fund_code": row["fund_code"], "calc_date": row["calc_date"],
             "future_return": row["score"] + rng.normal(0, 0.001)}  # tiny noise
            for _, row in scores.iterrows()
        ])
        result = compute_ic(scores, future)
        assert result["ic_count"] == 3
        assert result["ic_mean"] is not None and result["ic_mean"] > 0.5
        assert result["monotonicity"] is True
        assert result["group_metrics"]["future_return"]

    def test_compute_ic_reports_grouped_forward_risk_metrics(self):
        """Grouped backtests include 1Y return, drawdown, and Sharpe monotonicity."""
        from fund_research.analysis.scoring import compute_ic

        rows = []
        future_rows = []
        for d in range(3):
            calc_date = date(2024, (d * 3 + 3), 30)
            for f in range(20):
                score = float(f)
                rows.append({
                    "fund_code": f"{f:06d}",
                    "calc_date": calc_date,
                    "score": score,
                })
                future_rows.append({
                    "fund_code": f"{f:06d}",
                    "calc_date": calc_date,
                    "future_return": score / 100.0,
                    "future_max_drawdown": (20 - f) / 100.0,
                    "future_sharpe": score / 10.0,
                })

        result = compute_ic(pd.DataFrame(rows), pd.DataFrame(future_rows))

        assert set(result["group_metrics"]) == {
            "future_return",
            "future_max_drawdown",
            "future_sharpe",
        }
        assert result["monotonicity_checks"] == {
            "future_return": True,
            "future_max_drawdown": True,
            "future_sharpe": True,
        }

    def test_compute_ic_insufficient_data(self):
        """Less than 10 merged rows → null results with warning."""
        from fund_research.analysis.scoring import compute_ic

        scores = pd.DataFrame([
            {"fund_code": "A", "calc_date": date(2024, 3, 31), "score": 50},
        ])
        future = pd.DataFrame([
            {"fund_code": "A", "calc_date": date(2024, 3, 31), "future_return": 0.05},
        ])
        result = compute_ic(scores, future)
        assert result["ic_mean"] is None
        assert any("样本不足" in w for w in result["warnings"])

    def test_compute_ic_empty(self):
        """Empty inputs return null results."""
        from fund_research.analysis.scoring import compute_ic

        result = compute_ic(pd.DataFrame(), pd.DataFrame())
        assert result["ic_mean"] is None
        assert any("数据不足" in w for w in result["warnings"])

    def test_quarterly_dates(self):
        """Quarterly date generation covers expected range."""
        from fund_research.experiments.runner import _quarterly_dates

        dates = _quarterly_dates(date(2023, 1, 1), date(2024, 12, 31))
        assert len(dates) == 8
        assert dates[0] == date(2023, 3, 31)
        assert dates[-1] == date(2024, 12, 31)
        assert all(d.month in {3, 6, 9, 12} for d in dates)
        assert all(d.day in {30, 31} for d in dates)

    def test_quarterly_dates_partial_range(self):
        """Partial year range gives correct subset."""
        from fund_research.experiments.runner import _quarterly_dates

        dates = _quarterly_dates(date(2023, 5, 1), date(2023, 10, 31))
        assert dates == [date(2023, 6, 30), date(2023, 9, 30)]
