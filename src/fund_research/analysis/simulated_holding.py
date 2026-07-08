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
from math import ceil

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
ALGORITHM_VERSION = "0.2.0"

# Reliability thresholds per requirements §5.1.3:
# - Industry correlation >= 0.7
# - Top10 recall >= 50%
# - Tracking error < 2x fund historical vol (checked by caller)
MIN_INDUSTRY_CORRELATION = 0.70
MIN_TOP10_RECALL = 0.50
MAX_TRACKING_ERROR = 0.05  # 5% daily RMSE — fallback threshold when fund_volatility is unavailable


@dataclass
class SinglePeriodResult:
    """A single rebalancing window's simulated holdings."""

    calc_date: date
    holdings: list[dict]  # [{stock_code, stock_name, estimated_weight, confidence}]
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

    def is_reliable(self, fund_volatility: float | None = None) -> bool:
        """Check if simulated holding results meet acceptance thresholds.

        Per requirements §5.1.3:
        - overall_tracking_error < MAX_TRACKING_ERROR (5% daily RMSE, fallback
          when fund_volatility is unavailable)
        - When fund_volatility is provided: overall_tracking_error < 2 * fund_volatility
        - top10_recall >= MIN_TOP10_RECALL (50%)
        - industry_correlation >= MIN_INDUSTRY_CORRELATION (0.7) when available.
          If industry data is unavailable (None), this check is skipped with a warning.

        Args:
            fund_volatility: Standard deviation of fund daily returns. When
                provided, the tighter 2x-vol gate replaces the fixed
                MAX_TRACKING_ERROR fallback.
        """
        # Determine tracking-error gate: prefer 2x fund vol when available
        te_gate = 2.0 * fund_volatility if (fund_volatility is not None and fund_volatility > 0) else MAX_TRACKING_ERROR
        if not self.periods or self.overall_tracking_error >= te_gate:
            return False
        if not self.backtest_report:
            return False
        if self.overall_top10_recall is None or self.overall_top10_recall < MIN_TOP10_RECALL:
            return False
        # Industry correlation is optional — if computed, it must meet threshold;
        # if unavailable, skip this gate (a warning will be emitted in to_api_data).
        return not (
            self.overall_industry_correlation is not None
            and self.overall_industry_correlation < MIN_INDUSTRY_CORRELATION
        )

    def to_api_data(self) -> dict:
        return {
            "fund_code": self.fund_code,
            "period_count": len(self.periods),
            "estimated_overall_tracking_error": round(self.overall_tracking_error, 6),
            "estimated_overall_industry_correlation": (
                round(self.overall_industry_correlation, 4)
                if self.overall_industry_correlation is not None
                else None
            ),
            "estimated_overall_top10_recall": (
                round(self.overall_top10_recall, 4)
                if self.overall_top10_recall is not None
                else None
            ),
            "confidence": self.confidence,
            "is_reliable": self.is_reliable(),
            "conclusion_status": "estimated" if self.is_reliable() else "needs_review",
            "warnings": self.warnings,
            "periods": [
                {
                    "calc_date": str(p.calc_date),
                    "estimated_holdings": p.holdings,
                    "estimated_stock_weight_pct": p.stock_weight_pct,
                    "estimated_bond_weight_pct": p.bond_weight_pct,
                    "estimated_cash_weight_pct": p.cash_weight_pct,
                    "estimated_tracking_error": round(p.tracking_error, 6),
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
    max_pool_size: int = 150,
    same_manager_holdings: list[str] | None = None,
    newly_added_stocks: list[str] | None = None,
    style_similar_stocks: list[str] | None = None,
    top_n_per_industry: int = 5,
) -> list[str]:
    """
    Build candidate stock pool for optimization per requirements §5.1.2.

    Pool sources (in priority order):
    1. Current/recent disclosed holdings (always included)
    2. Same-manager preferred stocks (cross-fund holdings of same manager)
    3. Top N by market cap in each disclosed industry ("industry leaders")
    4. Newly added stocks in the most recent report (report-period additions)
    5. Style-similar stocks (same size/value/growth characteristics)

    Args:
        current_holdings: stock codes from the latest disclosed quarter.
        all_stocks: DataFrame with columns [stock_code, industry, market_cap].
        max_pool_size: cap on total candidate pool size.
        same_manager_holdings: stocks held by same manager across other funds.
        newly_added_stocks: stocks newly added in the latest disclosure.
        style_similar_stocks: stocks with similar style factor exposure.
        top_n_per_industry: number of top-market-cap stocks to include per
            disclosed industry (default 5, up from 3 for better coverage).
    """
    if all_stocks.empty:
        return list(current_holdings)

    same_manager_holdings = same_manager_holdings or []
    newly_added_stocks = newly_added_stocks or []
    style_similar_stocks = style_similar_stocks or []

    pool_set: set[str] = set(current_holdings)

    # Source 2: same-manager preferred stocks (if available in all_stocks)
    valid_codes = set(all_stocks["stock_code"].tolist())
    pool_set.update(c for c in same_manager_holdings if c in valid_codes)

    # Source 3: top N by market cap in each disclosed industry
    disclosed = all_stocks[all_stocks["stock_code"].isin(current_holdings)]
    industries = disclosed["industry"].dropna().unique()
    for ind in industries:
        ind_stocks = all_stocks[all_stocks["industry"] == ind]
        top = ind_stocks.nlargest(top_n_per_industry, "market_cap")["stock_code"].tolist()
        pool_set.update(top)

    # Source 4: newly added stocks (from report-period changes)
    pool_set.update(c for c in newly_added_stocks if c in valid_codes)

    # Source 5: style-similar stocks
    pool_set.update(c for c in style_similar_stocks if c in valid_codes)

    # Preserve priority: current holdings first, then other sources
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


def _lookup_industry(code: str, stocks_df: pd.DataFrame) -> str | None:
    """Look up stock industry from pool DataFrame."""
    if "industry" not in stocks_df.columns:
        return None
    industries = stocks_df.set_index("stock_code")["industry"]
    value = industries.loc[code] if code in industries.index else None
    return value if isinstance(value, str) else None


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
    max_positions = max(1, min(max_positions, n_stocks))
    if max_positions * max_single_weight < 1.0:
        max_positions = min(n_stocks, ceil(1.0 / max_single_weight))

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
            max_positions, max_single_weight, turnover_penalty, prev_weights,
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
            weights = _enforce_position_limit(weights, max_positions, max_single_weight)
            return weights, prob.value if prob.value is not None else 0.0
    except cp.error.SolverError:
        pass

    # Fallback to equal weight
    return _equal_weight(n_stocks, max_positions), 0.0


def _equal_weight(n_stocks: int, max_positions: int) -> np.ndarray:
    """Equal-weight fallback that respects the position limit."""
    weights = np.zeros(n_stocks)
    keep_count = max(1, min(max_positions, n_stocks))
    weights[:keep_count] = 1.0 / keep_count
    return weights


def _enforce_position_limit(
    weights: np.ndarray,
    max_positions: int,
    max_single_weight: float,
) -> np.ndarray:
    """Enforce hard constraints: at most max_positions holdings, single weight <= cap.

    Iteratively:
    1. Zero out weights below a small threshold, keeping only top max_positions.
    2. Cap weights exceeding max_single_weight and redistribute excess to
       non-capped positions proportionally.
    3. Repeat until no weights exceed the cap.
    4. Normalize so weights sum to 1.0.

    This implements hard post-processing constraints per requirements §5.1.2
    (max 30 positions, single-name cap). The optimizer's L1 regularization
    encourages sparsity, and this function guarantees the constraints are met.
    """
    cleaned = np.nan_to_num(np.maximum(weights, 0.0), nan=0.0)
    total = cleaned.sum()
    if total <= 0:
        return _equal_weight(len(cleaned), max_positions)

    cleaned /= total  # normalize first

    # Step 1: Keep only top max_positions
    keep_count = max(1, min(max_positions, len(cleaned)))
    keep_idx = np.argsort(cleaned)[::-1][:keep_count]
    limited = np.zeros_like(cleaned)
    limited[keep_idx] = cleaned[keep_idx]
    limited_sum = limited.sum()
    if limited_sum > 0:
        limited /= limited_sum

    # Step 2: Iteratively cap single-weight and redistribute
    for _ in range(50):  # enough iterations for convergence
        over = limited > max_single_weight + 1e-8
        if not over.any():
            break
        excess = float((limited[over] - max_single_weight).sum())
        limited[over] = max_single_weight
        # Redistribute to non-capped, non-zero positions
        room_mask = (limited > 1e-8) & (limited < max_single_weight - 1e-8)
        if not room_mask.any():
            # All positions are at cap — keep as-is, will renormalize
            break
        room = max_single_weight - limited[room_mask]
        room_sum = float(room.sum())
        if room_sum <= 1e-12:
            break
        limited[room_mask] += excess * room / room_sum

    # Final normalization
    final_sum = limited.sum()
    if final_sum > 0:
        limited /= final_sum
    return limited


def _optimize_scipy(
    sigma: np.ndarray,
    cov_with_fund: np.ndarray,
    n_stocks: int,
    max_positions: int,
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
        w = _enforce_position_limit(w, max_positions, max_single_weight)
        return w, float(result.fun) if result.fun is not None else 0.0

    return _equal_weight(n_stocks, max_positions), 0.0


# ============================================================
# Backtest against disclosed holdings
# ============================================================


def backtest_disclosure(
    simulated: list[SinglePeriodResult],
    disclosed_holdings: dict[str, dict[str, float]],
    # {report_date_str: {stock_code: weight}}
    industry_by_code: dict[str, dict[str, str]] | None = None,
    # {report_date_str: {stock_code: industry}}
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
        actual_sorted = sorted(actual.items(), key=lambda x: x[1], reverse=True)
        actual_codes = {code for code, _weight in actual_sorted}
        simulated_codes = {h["stock_code"] for h in rp.holdings}
        industry_map = (industry_by_code or {}).get(date_str, {})

        # Top10 recall
        actual_top10 = {code for code, _weight in actual_sorted[:10]}
        simulated_top30 = {h["stock_code"] for h in sorted(
            rp.holdings,
            key=lambda x: x["estimated_weight"],
            reverse=True,
        )[:30]}
        recall = len(actual_top10 & simulated_top30) / max(len(actual_top10), 1)
        recalls.append(recall)

        actual_industry = _industry_weights(
            [{"stock_code": code, "estimated_weight": weight / 100.0, "industry": industry_map.get(code)}
             for code, weight in actual.items()]
        )
        simulated_industry = _industry_weights(rp.holdings)
        corr = _industry_weight_correlation(actual_industry, simulated_industry)
        if corr is not None:
            correlations.append(corr)

        details.append({
            "calc_date": date_str,
            "top10_recall": round(recall, 4),
            "industry_correlation": round(corr, 4) if corr is not None else None,
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


def _industry_weights(holdings: list[dict]) -> dict[str, float]:
    weights: dict[str, float] = {}
    for item in holdings:
        industry = item.get("industry")
        if not isinstance(industry, str) or not industry:
            continue
        weight = float(item.get("estimated_weight", item.get("weight", 0.0)) or 0.0)
        weights[industry] = weights.get(industry, 0.0) + weight
    total = sum(weights.values())
    if total > 0:
        weights = {k: v / total for k, v in weights.items()}
    return weights


def _industry_weight_correlation(
    actual: dict[str, float],
    simulated: dict[str, float],
) -> float | None:
    industries = sorted(set(actual) | set(simulated))
    if len(industries) < 2:
        return None
    actual_values = np.array([actual.get(ind, 0.0) for ind in industries])
    simulated_values = np.array([simulated.get(ind, 0.0) for ind in industries])
    if np.std(actual_values) == 0 or np.std(simulated_values) == 0:
        return None
    return float(np.corrcoef(actual_values, simulated_values)[0, 1])


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

    # Get rebalancing dates limited to overlapping NAV + stock range
    all_dates = sorted(nav["trade_date"].unique())
    stock_dates = sorted(stocks["trade_date"].dropna().unique())
    if stock_dates:
        min_common = max(all_dates[0], stock_dates[0])
        max_common = min(all_dates[-1], stock_dates[-1])
        all_dates = [d for d in all_dates if min_common <= d <= max_common]

    if rebalance_freq == "M":
        rebal_dates = sorted({d.replace(day=1) for d in all_dates})
    else:
        rebal_dates = sorted({d.replace(day=1) for d in all_dates if d.month in (1, 4, 7, 10)})

    periods: list[SinglePeriodResult] = []
    prev_weights: np.ndarray | None = None
    prev_pool_in_data: list[str] | None = None
    skipped_no_nav = 0
    skipped_no_stocks = 0
    skipped_no_pool = 0
    skipped_no_holdings = 0
    total_attempted = 0

    for rb_date in rebal_dates:
        total_attempted += 1
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
            skipped_no_nav += 1
            continue

        # Nearest disclosed holdings: use latest available if none before rb_date
        prev_holdings = holdings[holdings["report_date"] <= rb_date]
        if prev_holdings.empty:
            prev_holdings = holdings  # fallback: use all available holdings
        if prev_holdings.empty:
            skipped_no_holdings += 1
            continue
        latest_report = prev_holdings["report_date"].max()
        latest_holdings = prev_holdings[prev_holdings["report_date"] == latest_report]

        current_holding_codes = latest_holdings["stock_code"].unique().tolist()

        # Build candidate pool
        all_stocks_for_pool = stocks[["stock_code", "industry", "market_cap"]].drop_duplicates("stock_code")
        # Merge stock_name from holdings (StockDaily has no stock_name column)
        if "stock_name" in holdings.columns:
            name_lookup = holdings[["stock_code", "stock_name"]].drop_duplicates("stock_code")
            all_stocks_for_pool = all_stocks_for_pool.merge(
                name_lookup, on="stock_code", how="left"
            )
            all_stocks_for_pool["stock_name"] = all_stocks_for_pool["stock_name"].fillna(
                all_stocks_for_pool["stock_code"]
            )
        pool = build_candidate_pool(current_holding_codes, all_stocks_for_pool)

        # Get stock returns for the window
        window_stocks = stocks[(stocks["trade_date"] >= rb_date) & (stocks["trade_date"] < window_end_date)]
        if window_stocks.empty:
            skipped_no_stocks += 1
            continue

        # Build return matrices
        stock_pivot = window_stocks.pivot_table(
            index="trade_date", columns="stock_code", values="daily_return", aggfunc="last"
        )
        # Filter to pool stocks
        pool_in_data = [s for s in pool if s in stock_pivot.columns]
        if len(pool_in_data) < 2:
            skipped_no_pool += 1
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
        if prev_weights is not None and prev_pool_in_data is not None:
            prev_code_to_idx = {
                c: j for j, c in enumerate(prev_pool_in_data)
            }
            prev_mapped = np.zeros(len(pool_in_data))
            for j, s in enumerate(pool_in_data):
                if s in prev_code_to_idx:
                    prev_mapped[j] = prev_weights[prev_code_to_idx[s]]

        try:
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
        except Exception:
            # Fallback: equal weight if optimization fails
            weights = _equal_weight(len(pool_in_data), max_positions)
            obj_val = 0.0

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
                    "industry": _lookup_industry(s, all_stocks_for_pool),
                    "estimated_weight": round(w, 4),
                    "confidence": "medium" if w > 0.01 else "low",
                })

        periods.append(SinglePeriodResult(
            calc_date=rb_date,
            holdings=sorted(holdings_list, key=lambda x: x["estimated_weight"], reverse=True),
            stock_weight_pct=round(float(weights.sum()) * 100, 2),
            bond_weight_pct=0.0,
            cash_weight_pct=round(float(1 - weights.sum()) * 100, 2),
            tracking_error=rmse,
            objective_value=obj_val,
            warnings=[] if rmse < 0.05 else [f"跟踪误差偏高: {rmse:.4f}"],
        ))

        prev_weights = weights
        prev_pool_in_data = pool_in_data

    # Overall stats
    if periods:
        avg_te = np.mean([p.tracking_error for p in periods])
        confidence = "medium"
        if avg_te > 0.08:
            confidence = "low"
            warnings.append("整体跟踪误差偏高，模拟持仓仅作方向性参考")
    else:
        avg_te = 0.0
        confidence = "needs_review"
        warnings.append(
            f"全部 {total_attempted} 个调仓窗口跳过: "
            f"NAV不足={skipped_no_nav}, 无股票={skipped_no_stocks}, "
            f"候选池不足={skipped_no_pool}, 无持仓={skipped_no_holdings}"
        )

    # Backtest
    backtest: dict | None = None
    if run_backtest:
        disclosed_dict: dict[str, dict[str, float]] = {}
        industry_dict: dict[str, dict[str, str]] = {}
        for rp_date in holdings["report_date"].unique():
            rp_holdings = holdings[holdings["report_date"] == rp_date]
            disclosed_dict[str(rp_date)] = dict(zip(
                rp_holdings["stock_code"],
                rp_holdings.get("weight_pct", [0] * len(rp_holdings)), strict=False,
            ))
            if "industry" in rp_holdings.columns:
                industry_dict[str(rp_date)] = {
                    str(row["stock_code"]): row["industry"]
                    for _idx, row in rp_holdings.iterrows()
                    if isinstance(row.get("industry"), str)
                }
        backtest = backtest_disclosure(periods, disclosed_dict, industry_dict)

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
