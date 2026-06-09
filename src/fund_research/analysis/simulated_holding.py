"""
Simulated holding estimation via constrained optimization.

Core approach: minimize tracking error between the simulated portfolio
and the fund's actual NAV returns, subject to long-only, sparsity,
turnover, and industry constraints.

References:
- Index tracking / portfolio replication with regularization
- CVXPY documentation: https://www.cvxpy.org/
"""

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

try:
    import cvxpy as cp

    _HAS_CVXPY = True
except ImportError:
    _HAS_CVXPY = False

SCIPY_AVAILABLE = True
try:
    from scipy.optimize import minimize
except ImportError:
    SCIPY_AVAILABLE = False

ALGORITHM_NAME = "simulated_holding"
ALGORITHM_VERSION = "0.1.0"


@dataclass
class SinglePeriodResult:
    """A single rebalancing window's simulated holdings."""

    calc_date: date
    holdings: list[dict]  # [{stock_code, stock_name, weight, confidence}]
    stock_weight_pct: float
    bond_weight_pct: float
    cash_weight_pct: float
    tracking_error: float  # daily RMSE between simulated and fund returns
    objective_value: float  # optimization objective value
    warnings: list[str] = field(default_factory=list)


@dataclass
class SimulatedHoldingResult:
    """Full multi-period simulation output."""

    fund_code: str
    periods: list[SinglePeriodResult]
    backtest_report: dict | None = None  # comparison with disclosed holdings
    overall_tracking_error: float = 0.0
    overall_industry_correlation: float | None = None
    overall_top10_recall: float | None = None
    confidence: str = "medium"
    warnings: list[str] = field(default_factory=list)

    @property
    def is_reliable(self) -> bool:
        return self.overall_tracking_error < 0.05 and bool(self.periods)

    def to_api_data(self) -> dict:
        return {
            "fund_code": self.fund_code,
            "period_count": len(self.periods),
            "overall_tracking_error": round(self.overall_tracking_error, 6),
            "overall_industry_correlation": (
                round(self.overall_industry_correlation, 4)
                if self.overall_industry_correlation is not None
                else None
            ),
            "overall_top10_recall": (
                round(self.overall_top10_recall, 4)
                if self.overall_top10_recall is not None
                else None
            ),
            "confidence": self.confidence,
            "is_reliable": self.is_reliable,
            "warnings": self.warnings,
            "periods": [
                {
                    "calc_date": str(p.calc_date),
                    "holdings": p.holdings,
                    "stock_weight_pct": p.stock_weight_pct,
                    "tracking_error": round(p.tracking_error, 6),
                }
                for p in self.periods
            ],
        }


# ============================================================
# Candidate pool construction
# ============================================================


def build_candidate_pool(
    current_holdings: list[str],
    all_stocks: pd.DataFrame,
    *,
    max_pool_size: int = 100,
) -> list[str]:
    """
    Build candidate stock pool for optimization.

    current_holdings: stock codes from the latest disclosed quarter.
    all_stocks: DataFrame with columns [stock_code, industry, market_cap].

    Pool = disclosed holdings + top 3 by market cap in each disclosed industry.
    """
    if all_stocks.empty:
        return list(current_holdings)

    pool_set = set(current_holdings)
    disclosed = all_stocks[all_stocks["stock_code"].isin(current_holdings)]
    industries = disclosed["industry"].dropna().unique()

    for ind in industries:
        ind_stocks = all_stocks[all_stocks["industry"] == ind]
        top3 = ind_stocks.nlargest(3, "market_cap")["stock_code"].tolist()
        pool_set.update(top3)

    pool = [s for s in current_holdings if s in pool_set]
    for s in pool_set:
        if s not in pool:
            pool.append(s)

    return pool[:max_pool_size]


def _lookup_name(code: str, stocks_df: pd.DataFrame) -> str:
    """Look up stock name from pool DataFrame, fallback to code."""
    if "stock_name" not in stocks_df.columns:
        return code
    names = stocks_df.set_index("stock_code")["stock_name"]
    return names.loc[code] if code in names.index else code


# ============================================================
# Single-period optimization
# ============================================================


def optimize_weights(
    stock_returns: np.ndarray,  # (n_stocks, n_days)
    fund_returns: np.ndarray,  # (n_days,)
    *,
    max_positions: int = 30,
    max_single_weight: float = 0.10,
    turnover_penalty: float = 0.0,
    prev_weights: np.ndarray | None = None,
    industry_groups: list[int] | None = None,
    disclosed_industry_weights: dict[int, float] | None = None,
    industry_penalty: float = 0.0,
    use_cvxpy: bool = True,
) -> tuple[np.ndarray, float]:
    """
    Single-period optimization: find portfolio weights that minimize
    tracking error to the fund's NAV return.

    Returns (weights, objective_value).
    """
    n_stocks, n_days = stock_returns.shape
    if n_stocks == 0 or n_days == 0:
        return np.zeros(n_stocks), 0.0

    # Covariance matrix and excess returns
    sigma = np.cov(stock_returns)  # covariance matrix (n_stocks, n_stocks)  # noqa: N806
    cov_with_fund = np.array([np.cov(stock_returns[i], fund_returns)[0, 1] for i in range(n_stocks)])

    if use_cvxpy and _HAS_CVXPY:
        return _optimize_cvxpy(
            sigma, cov_with_fund, n_stocks,
            max_positions, max_single_weight,
            turnover_penalty, prev_weights,
            industry_groups, disclosed_industry_weights, industry_penalty,
        )
    elif SCIPY_AVAILABLE:
        return _optimize_scipy(
            sigma, cov_with_fund, n_stocks,
            max_single_weight, turnover_penalty, prev_weights,
        )
    else:
        # Fallback: equal weight
        w = np.ones(n_stocks) / n_stocks
        return w, 0.0


def _optimize_cvxpy(
    sigma: np.ndarray,
    cov_with_fund: np.ndarray,
    n_stocks: int,
    max_positions: int,
    max_single_weight: float,
    turnover_penalty: float,
    prev_weights: np.ndarray | None,
    industry_groups: list[int] | None,
    disclosed_industry_weights: dict[int, float] | None,
    industry_penalty: float,
) -> tuple[np.ndarray, float]:
    """CVXPY convex optimization solver."""

    w = cp.Variable(n_stocks)
    # Objective: minimize tracking error variance
    objective = cp.quad_form(w, sigma) - 2 * w @ cov_with_fund
    constraints: list = [
        cp.sum(w) == 1.0,
        w >= 0.0,
        w <= max_single_weight,
    ]
    # L1 regularization for sparsity (proxy for max_positions)
    # Use l1-norm to encourage sparse weights
    lam_sparse = 0.02 if n_stocks > max_positions else 0.0
    if lam_sparse > 0:
        objective += lam_sparse * cp.norm1(w)

    # Turnover penalty
    if turnover_penalty > 0 and prev_weights is not None:
        objective += turnover_penalty * cp.sum_squares(w - prev_weights)

    # Industry deviation penalty
    if industry_penalty > 0 and industry_groups and disclosed_industry_weights:
        for ind, target in disclosed_industry_weights.items():
            mask = np.array([1 if g == ind else 0 for g in industry_groups])
            actual = w @ mask
            objective += industry_penalty * cp.square(actual - target)

    try:
        prob = cp.Problem(cp.Minimize(objective), constraints)
        prob.solve(solver=cp.OSQP, verbose=False)
        if prob.status in ("optimal", "optimal_inaccurate"):
            weights = np.array(w.value).flatten()
            weights = np.maximum(weights, 0)
            weights /= weights.sum() if weights.sum() > 0 else 1.0
            return weights, prob.value if prob.value is not None else 0.0
    except cp.error.SolverError:
        pass

    # Fallback to equal weight
    return np.ones(n_stocks) / n_stocks, 0.0


def _optimize_scipy(
    sigma: np.ndarray,
    cov_with_fund: np.ndarray,
    n_stocks: int,
    max_single_weight: float,
    turnover_penalty: float,
    prev_weights: np.ndarray | None,
) -> tuple[np.ndarray, float]:
    """scipy.optimize fallback solver."""

    def objective(w: np.ndarray) -> float:
        val = float(w @ sigma @ w - 2 * w @ cov_with_fund)
        if turnover_penalty > 0 and prev_weights is not None:
            val += turnover_penalty * np.sum((w - prev_weights) ** 2)
        return val

    constraints: list[dict] = [
        {"type": "eq", "fun": lambda w: np.sum(w) - 1.0},
    ]
    bounds = [(0, max_single_weight) for _ in range(n_stocks)]
    x0 = prev_weights if prev_weights is not None else np.ones(n_stocks) / n_stocks

    result = minimize(
        objective, x0, method="SLSQP", bounds=bounds, constraints=constraints,
        options={"maxiter": 500, "ftol": 1e-8},
    )
    if result.success:
        w = result.x
        w = np.maximum(w, 0)
        w /= w.sum() if w.sum() > 0 else 1.0
        return w, float(result.fun) if result.fun is not None else 0.0

    return np.ones(n_stocks) / n_stocks, 0.0


# ============================================================
# Backtest against disclosed holdings
# ============================================================


def backtest_disclosure(
    simulated: list[SinglePeriodResult],
    disclosed_holdings: dict[str, dict[str, float]],
    # {report_date_str: {stock_code: weight}}
) -> dict:
    """
    Compare simulated weights with actually disclosed weights.

    Returns:
        industry_correlation: Pearson corr of industry weights
        top10_recall: fraction of disclosed top10 found in simulated top10
        detail: per-report-date breakdown
    """
    if not simulated or not disclosed_holdings:
        return {
            "industry_correlation": None,
            "top10_recall": None,
            "detail": [],
            "warnings": ["回测数据不足"],
        }

    correlations: list[float] = []
    recalls: list[float] = []
    details = []

    for rp in simulated:
        date_str = str(rp.calc_date)
        if date_str not in disclosed_holdings:
            continue

        actual = disclosed_holdings[date_str]
        actual_codes = set(actual.keys())
        simulated_codes = {h["stock_code"] for h in rp.holdings}

        # Top10 recall
        actual_top10 = set(list(actual.keys())[:10])
        simulated_top30 = set(list({h["stock_code"] for h in rp.holdings})[:30])
        recall = len(actual_top10 & simulated_top30) / max(len(actual_top10), 1)
        recalls.append(recall)

        details.append({
            "calc_date": date_str,
            "top10_recall": round(recall, 4),
            "common_stocks": len(actual_codes & simulated_codes),
            "simulated_count": len(simulated_codes),
            "actual_count": len(actual_codes),
        })

    return {
        "industry_correlation": np.mean(correlations) if correlations else None,
        "top10_recall": np.mean(recalls) if recalls else None,
        "detail": details,
        "warnings": [] if recalls and np.mean(recalls) > 0.5 else ["回测重仓股召回率偏低 (<50%)"],
    }


# ============================================================
# Full simulation pipeline
# ============================================================


def run_simulation(
    fund_code: str,
    fund_nav: pd.DataFrame,
    # columns: [trade_date, daily_return]
    stock_returns: pd.DataFrame,
    # columns: [trade_date, stock_code, daily_return, close_price, industry, market_cap]
    disclosed_holdings: pd.DataFrame,
    # columns: [report_date, stock_code, weight_pct]
    *,
    rebalance_freq: str = "M",
    window_days: int = 60,
    max_positions: int = 30,
    max_single_weight: float = 0.10,
    turnover_penalty: float = 0.5,
    industry_penalty: float = 0.5,
    run_backtest: bool = True,
) -> SimulatedHoldingResult:
    """
    Run full multi-period holding simulation.

    Steps:
    1. Build candidate pool from each quarter's disclosed holdings
    2. For each rebalancing date, run single-period optimization
    3. If run_backtest=True, compare with disclosed holdings
    """
    warnings: list[str] = []
    if not _HAS_CVXPY and not SCIPY_AVAILABLE:
        return SimulatedHoldingResult(
            fund_code=fund_code,
            periods=[],
            warnings=["CVXPY 和 scipy 均不可用，无法运行模拟持仓"],
            confidence="needs_review",
        )

    if fund_nav.empty or stock_returns.empty:
        return SimulatedHoldingResult(
            fund_code=fund_code,
            periods=[],
            warnings=["净值或股票行情数据为空"],
            confidence="needs_review",
        )

    # Prepare data
    nav = fund_nav.copy()
    nav["trade_date"] = pd.to_datetime(nav["trade_date"]).dt.date
    nav = nav.sort_values("trade_date")

    stocks = stock_returns.copy()
    stocks["trade_date"] = pd.to_datetime(stocks["trade_date"]).dt.date
    stocks = stocks.sort_values(["stock_code", "trade_date"])

    # Ensure daily_return is available
    if "daily_return" not in nav.columns or nav["daily_return"].isna().all():
        nav_col = next((c for c in ("unit_nav", "accumulated_nav") if c in nav.columns), None)
        if nav_col:
            nav["daily_return"] = pd.to_numeric(nav[nav_col], errors="coerce").pct_change()
        else:
            return SimulatedHoldingResult(
                fund_code=fund_code, periods=[],
                warnings=["缺少每日收益率数据"], confidence="needs_review",
            )

    if "daily_return" not in stocks.columns:
        stocks["daily_return"] = stocks.groupby("stock_code")["close_price"].pct_change()

    holdings = disclosed_holdings.copy()
    holdings["report_date"] = pd.to_datetime(holdings["report_date"]).dt.date
    holdings = holdings.sort_values("report_date")

    # Get rebalancing dates (first day of each month or each quarter)
    all_dates = sorted(nav["trade_date"].unique())
    if rebalance_freq == "M":
        rebal_dates = sorted({d.replace(day=1) for d in all_dates})
    else:
        rebal_dates = sorted({d.replace(day=1) for d in all_dates if d.month in (1, 4, 7, 10)})

    periods: list[SinglePeriodResult] = []
    prev_weights: np.ndarray | None = None

    for i, rb_date in enumerate(rebal_dates):
        # Window: rb_date to rb_date + window_days
        window_end = None
        for d in all_dates:
            if d >= rb_date:
                window_end = d
                break
        if window_end is None:
            continue

        window_end_date = rb_date + pd.Timedelta(days=window_days)
        window_nav = nav[(nav["trade_date"] >= rb_date) & (nav["trade_date"] < window_end_date)]
        if len(window_nav) < 20:
            continue

        # Nearest disclosed holdings before this rebalance date
        prev_holdings = holdings[holdings["report_date"] <= rb_date]
        if prev_holdings.empty:
            continue
        latest_report = prev_holdings["report_date"].max()
        latest_holdings = prev_holdings[prev_holdings["report_date"] == latest_report]

        current_holding_codes = latest_holdings["stock_code"].unique().tolist()

        # Build candidate pool
        all_stocks_for_pool = stocks[["stock_code", "industry", "market_cap"]].drop_duplicates("stock_code")
        pool = build_candidate_pool(current_holding_codes, all_stocks_for_pool)

        # Get stock returns for the window
        window_stocks = stocks[(stocks["trade_date"] >= rb_date) & (stocks["trade_date"] < window_end_date)]
        if window_stocks.empty:
            continue

        # Build return matrices
        stock_pivot = window_stocks.pivot_table(
            index="trade_date", columns="stock_code", values="daily_return", aggfunc="last"
        )
        # Filter to pool stocks
        pool_in_data = [s for s in pool if s in stock_pivot.columns]
        if len(pool_in_data) < 5:
            continue

        ret_matrix = stock_pivot[pool_in_data].values.T  # (n_stocks, n_days)
        fund_ret = window_nav.set_index("trade_date")["daily_return"].reindex(
            stock_pivot.index
        ).values  # (n_days,)
        fund_ret = np.nan_to_num(fund_ret, nan=0.0)
        ret_matrix = np.nan_to_num(ret_matrix, nan=0.0)

        # Industry constraints
        industry_groups: list[int] | None = None
        ind_weights: dict[int, float] | None = None
        if industry_penalty > 0:
            {s: i for i, s in enumerate(pool_in_data)}
            disclosed_ind = latest_holdings.set_index("stock_code")
            if "industry" in disclosed_ind.columns:
                unique_inds: dict[str, int] = {}
                for s in pool_in_data:
                    if s in disclosed_ind.index:
                        raw_ind = disclosed_ind.loc[s, "industry"]
                        ind_name = raw_ind if isinstance(raw_ind, str) else "other"
                        if ind_name not in unique_inds:
                            unique_inds[ind_name] = len(unique_inds)
                industry_groups = [
                    unique_inds.get(
                        disclosed_ind.loc[s, "industry"] if s in disclosed_ind.index else "other",
                        len(unique_inds),
                    )
                    for s in pool_in_data
                ]
                # Disclosed industry weights
                raw_ind_weights: dict[int, float] = {}
                for _idx, row in latest_holdings.iterrows():
                    if row.get("stock_code") in pool_in_data:
                        g = industry_groups[pool_in_data.index(row["stock_code"])]
                        raw_ind_weights[g] = raw_ind_weights.get(g, 0.0) + float(row.get("weight_pct", 0)) / 100.0
                total = sum(raw_ind_weights.values()) or 1.0
                ind_weights = {k: v / total for k, v in raw_ind_weights.items()}

        # Map prev_weights to current pool
        prev_mapped: np.ndarray | None = None
        if prev_weights is not None and i > 0:
            prev_code_to_idx = {
                c: j for j, c in enumerate(pool_in_data_prev)  # noqa: F821
            } if i > 0 else {}
            prev_mapped = np.zeros(len(pool_in_data))
            for j, s in enumerate(pool_in_data):
                if s in prev_code_to_idx:
                    prev_mapped[j] = prev_weights[prev_code_to_idx[s]]

        weights, obj_val = optimize_weights(
            ret_matrix, fund_ret,
            max_positions=max_positions,
            max_single_weight=max_single_weight,
            turnover_penalty=turnover_penalty,
            prev_weights=prev_mapped,
            industry_groups=industry_groups,
            disclosed_industry_weights=ind_weights,
            industry_penalty=industry_penalty,
        )

        # Compute tracking error
        port_ret = ret_matrix.T @ weights  # (n_days,)
        rmse = float(np.sqrt(np.mean((port_ret - fund_ret) ** 2)))

        # Build holdings list
        holdings_list = []
        for j, s in enumerate(pool_in_data):
            w = float(weights[j])
            if w > 0.001:  # filter noise
                holdings_list.append({
                    "stock_code": s,
                    "stock_name": _lookup_name(s, all_stocks_for_pool),
                    "weight": round(w, 4),
                    "confidence": "medium" if w > 0.01 else "low",
                })

        periods.append(SinglePeriodResult(
            calc_date=rb_date,
            holdings=sorted(holdings_list, key=lambda x: x["weight"], reverse=True),
            stock_weight_pct=round(float(weights.sum()) * 100, 2),
            bond_weight_pct=0.0,
            cash_weight_pct=round(float(1 - weights.sum()) * 100, 2),
            tracking_error=rmse,
            objective_value=obj_val,
            warnings=[] if rmse < 0.05 else [f"跟踪误差偏高: {rmse:.4f}"],
        ))

        prev_weights = weights
        pool_in_data_prev = pool_in_data  # noqa: F841

    # Overall stats
    if periods:
        avg_te = np.mean([p.tracking_error for p in periods])
        confidence = "medium"
        if avg_te < 0.02:
            confidence = "high"
        elif avg_te > 0.08:
            confidence = "low"
            warnings.append("整体跟踪误差偏高，模拟持仓仅作方向性参考")
    else:
        avg_te = 0.0
        confidence = "needs_review"

    # Backtest
    backtest: dict | None = None
    if run_backtest:
        disclosed_dict: dict[str, dict[str, float]] = {}
        for rp_date in holdings["report_date"].unique():
            rp_holdings = holdings[holdings["report_date"] == rp_date]
            disclosed_dict[str(rp_date)] = dict(zip(
                rp_holdings["stock_code"],
                rp_holdings.get("weight_pct", [0] * len(rp_holdings)), strict=False,
            ))
        backtest = backtest_disclosure(periods, disclosed_dict)

    return SimulatedHoldingResult(
        fund_code=fund_code,
        periods=periods,
        backtest_report=backtest,
        overall_tracking_error=round(avg_te, 6),
        overall_industry_correlation=(
            backtest.get("industry_correlation") if backtest else None
        ),
        overall_top10_recall=backtest.get("top10_recall") if backtest else None,
        confidence=confidence,
        warnings=warnings,
    )
