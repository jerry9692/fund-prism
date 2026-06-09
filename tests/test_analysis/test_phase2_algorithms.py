"""Smoke tests for Phase 2 analysis algorithms."""


import numpy as np
import pandas as pd


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
        w, obj = optimize_weights(ret, f_ret, use_cvxpy=False)

        assert len(w) == 20
        assert abs(w.sum() - 1.0) < 0.01
        assert (w >= 0).all()

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
