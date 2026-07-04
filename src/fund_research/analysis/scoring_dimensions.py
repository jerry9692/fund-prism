"""
Real-data extraction for the 6 scoring dimensions beyond return/risk.

Each function accepts a DB session and fund_code, and returns a float
(or None when data is unavailable).  All values are oriented so that
"higher = better" — the scoring pipeline handles Z-score / percentile
standardisation downstream.

All functions accept an optional ``as_of_date`` parameter.  When provided,
only data with ``report_date/calc_date/start_date <= as_of_date`` is used.
This eliminates lookahead bias in backtests: scoring at eval_date T must
only see information available at or before T.
"""

from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.db.models import (
    FundDisclosedHoldings,
    FundManagerTenure,
    FundScale,
    HolderStructure,
    StaticAttributionResult,
    StyleExposureResult,
)

# ---------------------------------------------------------------------------
# alpha — selection + allocation effect from the most recent static attribution
# ---------------------------------------------------------------------------


def compute_alpha(db: Session, fund_code: str, as_of_date: date | None = None) -> float | None:
    """Compute Alpha dimension using Jensen's Alpha against the real benchmark index.

    This function loads the fund's daily returns and the benchmark index daily
    returns from the database, then computes Jensen's Alpha via OLS regression:
        r_fund - r_f = alpha + beta * (r_bench - r_f) + epsilon

    If benchmark index data is unavailable, it falls back to the static
    attribution (selection + allocation effect) as a proxy.

    Args:
        db: Database session
        fund_code: Fund code
        as_of_date: Only use data up to this date (prevents lookahead bias)

    Returns:
        Alpha score (higher is better), or None if insufficient data.
    """
    import numpy as np

    from fund_research.db.models import FundMain, FundNAV, StockDaily

    # 1. Determine the benchmark index symbol for this fund
    fund = db.scalar(select(FundMain).where(FundMain.fund_code == fund_code))
    if not fund:
        return None

    # Map common benchmark names to index codes stored in StockDaily
    benchmark_name = (fund.benchmark or "").lower()
    bench_symbol = _resolve_benchmark_symbol(benchmark_name)

    # 2. Load fund daily returns
    nav_stmt = select(FundNAV).where(FundNAV.fund_code == fund_code)
    if as_of_date is not None:
        nav_stmt = nav_stmt.where(FundNAV.trade_date <= as_of_date)
    nav_stmt = nav_stmt.order_by(FundNAV.trade_date)
    nav_rows = db.execute(nav_stmt).scalars().all()

    if len(nav_rows) < 20:
        # Insufficient NAV data — fall back to static attribution
        return _alpha_from_static_attribution(db, fund_code, as_of_date)

    fund_returns = pd.Series(
        {r.trade_date: r.daily_return for r in nav_rows if r.daily_return is not None}
    ).dropna()

    if len(fund_returns) < 20:
        return _alpha_from_static_attribution(db, fund_code, as_of_date)

    # 3. Load benchmark index daily returns
    alpha_score = None
    if bench_symbol:
        bench_stmt = select(StockDaily).where(StockDaily.stock_code == bench_symbol)
        if as_of_date is not None:
            bench_stmt = bench_stmt.where(StockDaily.trade_date <= as_of_date)
        bench_stmt = bench_stmt.order_by(StockDaily.trade_date)
        bench_rows = db.execute(bench_stmt).scalars().all()

        if len(bench_rows) >= 20:
            bench_returns = pd.Series(
                {r.trade_date: r.daily_return for r in bench_rows if r.daily_return is not None}
            ).dropna()

            if len(bench_returns) >= 20:
                # Align dates
                aligned = pd.DataFrame({"fund": fund_returns, "bench": bench_returns}).dropna()
                if len(aligned) >= 20:
                    risk_free_daily = 0.02 / 252  # 2% annualized
                    excess_fund = aligned["fund"] - risk_free_daily
                    excess_bench = aligned["bench"] - risk_free_daily

                    # OLS regression: excess_fund = alpha + beta * excess_bench
                    x = excess_bench.values
                    y = excess_fund.values
                    beta_num = np.sum((x - x.mean()) * (y - y.mean()))
                    beta_den = np.sum((x - x.mean()) ** 2)
                    if beta_den > 0:
                        beta = beta_num / beta_den
                        alpha = y.mean() - beta * x.mean()
                        # Annualize alpha (daily → annual)
                        alpha_score = float(alpha * 252)
                    else:
                        alpha_score = float(excess_fund.mean() * 252)

    # 4. Fall back to static attribution if no benchmark data
    if alpha_score is None:
        return _alpha_from_static_attribution(db, fund_code, as_of_date)

    return alpha_score


def _resolve_benchmark_symbol(benchmark_name: str) -> str | None:
    """Map a benchmark name to the index code stored in StockDaily."""
    # Common mappings: name → stock_code in StockDaily
    mappings = [
        ("沪深300", "sh000300"),
        ("300", "sh000300"),
        ("中证500", "sh000905"),
        ("500", "sh000905"),
        ("中证1000", "sh000852"),
        ("1000", "sh000852"),
        ("上证50", "sh000016"),
        ("创业板", "sz399006"),
        ("科创50", "sh000688"),
        ("中证全债", "sh000012"),
    ]
    for keyword, symbol in mappings:
        if keyword in benchmark_name:
            return symbol
    # Default to CSI 300
    if benchmark_name:
        return "sh000300"
    return None


def _alpha_from_static_attribution(
    db: Session, fund_code: str, as_of_date: date | None
) -> float | None:
    """Fallback: Alpha from static attribution (selection + allocation effect)."""
    stmt = select(StaticAttributionResult).where(
        StaticAttributionResult.fund_code == fund_code
    )
    if as_of_date is not None:
        stmt = stmt.where(StaticAttributionResult.report_date <= as_of_date)
    stmt = stmt.order_by(StaticAttributionResult.report_date.desc()).limit(1)

    row = db.scalar(stmt)
    if row is None:
        return None
    sel = row.selection_effect or 0.0
    alloc = row.allocation_effect or 0.0
    return sel + alloc


# ---------------------------------------------------------------------------
# trading — turnover estimated from consecutive semi-annual disclosures
# v0.4: REVERSED direction. IC diagnostics showed low-turnover funds
# underperform in A-shares (IC=-0.31), so higher turnover → higher score.
# A-share theme rotation is fast; active adjustment is rewarded.
# ---------------------------------------------------------------------------


def compute_trading(db: Session, fund_code: str, as_of_date: date | None = None) -> float | None:
    """Turnover estimated from the two most recent disclosed holding periods.

    When ``as_of_date`` is provided, only holdings with
    ``report_date <= as_of_date`` are considered.

    v0.4: Returns positive turnover (higher = better). IC diagnostics
    on 2021-2025 data showed the previous negation (low turnover = high
    score) produced IC=-0.31, i.e. completely inverted in A-shares.
    """
    stmt = (
        select(FundDisclosedHoldings)
        .where(FundDisclosedHoldings.fund_code == fund_code)
        .where(FundDisclosedHoldings.asset_type == "股票")
    )
    if as_of_date is not None:
        stmt = stmt.where(FundDisclosedHoldings.report_date <= as_of_date)
    stmt = stmt.order_by(FundDisclosedHoldings.report_date.desc()).limit(300)

    rows = db.scalars(stmt).all()
    if len(rows) < 2:
        return None

    dates = sorted({r.report_date for r in rows}, reverse=True)[:2]
    if len(dates) < 2:
        return None

    def _weight_map(report_date: date) -> dict[str, float]:
        period_rows = [r for r in rows if r.report_date == report_date]
        total = sum(r.weight_pct or 0 for r in period_rows)
        if total <= 0:
            return {}
        return {
            str(r.security_code): (r.weight_pct or 0) / total
            for r in period_rows
            if r.security_code
        }

    prev_w = _weight_map(dates[1])
    curr_w = _weight_map(dates[0])
    all_codes = set(prev_w) | set(curr_w)
    if not all_codes:
        return None

    turnover = sum(
        abs(curr_w.get(code, 0.0) - prev_w.get(code, 0.0))
        for code in all_codes
    ) / 2.0
    return turnover


# ---------------------------------------------------------------------------
# style_stability — mean cross-factor std of exposure values over time
# (lower std → higher score, so we negate)
# ---------------------------------------------------------------------------


def compute_style_stability(db: Session, fund_code: str, as_of_date: date | None = None) -> float | None:
    """Mean cross-factor std of style/industry exposure values over time.

    When ``as_of_date`` is provided, only exposures with
    ``calc_date <= as_of_date`` are considered.

    Supports both ``exposure_type='style'`` (regression-based) and
    ``exposure_type='industry'`` (disclosed industry allocation). The
    latter is the primary source when AKShare industry allocation data
    is available, since it does not require a separate style model.
    """
    stmt = (
        select(StyleExposureResult)
        .where(StyleExposureResult.fund_code == fund_code)
        .where(StyleExposureResult.exposure_type.in_(["style", "industry"]))
    )
    if as_of_date is not None:
        stmt = stmt.where(StyleExposureResult.calc_date <= as_of_date)
    stmt = stmt.order_by(StyleExposureResult.calc_date.desc()).limit(12)

    rows = db.scalars(stmt).all()
    if len(rows) < 2:
        return None

    by_factor: dict[str, list[float]] = {}
    for row in rows:
        if row.exposure_values:
            for factor, val in row.exposure_values.items():
                try:
                    by_factor.setdefault(factor, []).append(float(val))
                except (ValueError, TypeError):
                    continue

    stds = [float(np.std(vals)) for vals in by_factor.values() if len(vals) >= 2]
    if not stds:
        return None

    return -float(np.mean(stds))


# ---------------------------------------------------------------------------
# scale — adequacy score based on latest total NAV
# "golden zone" ≈ 1–50 B CNY; very small or very large funds are penalised
# ---------------------------------------------------------------------------


def compute_scale(db: Session, fund_code: str, as_of_date: date | None = None) -> float | None:
    """Scale adequacy score based on the latest total NAV.

    When ``as_of_date`` is provided, only scale records with
    ``report_date <= as_of_date`` are considered.
    """
    stmt = select(FundScale).where(FundScale.fund_code == fund_code)
    if as_of_date is not None:
        stmt = stmt.where(FundScale.report_date <= as_of_date)
    stmt = stmt.order_by(FundScale.report_date.desc()).limit(1)

    rows = db.scalars(stmt).all()
    if not rows or rows[0].total_nav is None:
        return None

    nav = float(rows[0].total_nav)
    if nav <= 0:
        return 0.0

    log_nav = float(np.log10(nav))

    if log_nav < -0.3:          # < 0.5 B
        score = max(0.0, 0.3 + log_nav)
    elif log_nav < 0.0:         # 0.5 – 1 B
        score = 0.5 + (log_nav + 0.3) * 0.5 / 0.3
    elif log_nav <= 1.7:        # 1 – 50 B  (golden zone)
        score = 1.0
    elif log_nav <= 2.0:        # 50 – 100 B
        score = 1.0 - (log_nav - 1.7) * 0.5 / 0.3
    else:                        # > 100 B
        score = max(0.2, 0.5 - (log_nav - 2.0) * 0.3)

    return score


# ---------------------------------------------------------------------------
# team — average tenure of current managers (longer → higher score)
# ---------------------------------------------------------------------------


def compute_team(db: Session, fund_code: str, as_of_date: date | None = None) -> float | None:
    """Average tenure of managers active at ``as_of_date``.

    When ``as_of_date`` is provided, a manager is considered "current" if
    ``start_date <= as_of_date`` and (``end_date is None`` or
    ``end_date > as_of_date``).  Tenure is measured up to ``as_of_date``.
    """
    stmt = select(FundManagerTenure).where(FundManagerTenure.fund_code == fund_code)
    if as_of_date is not None:
        stmt = stmt.where(FundManagerTenure.start_date <= as_of_date)
    stmt = stmt.order_by(FundManagerTenure.start_date.desc())

    rows = db.scalars(stmt).all()
    if not rows:
        return None

    if as_of_date is not None:
        # A manager is "current" at as_of_date if they started on or before
        # it and have not yet ended (or the stored is_current flag is True
        # and end_date is None / after as_of_date).
        current = [
            r for r in rows
            if r.end_date is None or r.end_date > as_of_date
        ]
        ref_date = as_of_date
    else:
        current = [r for r in rows if r.is_current]
        ref_date = date.today()

    if not current:
        return None

    tenures: list[float] = []
    for r in current:
        end = r.end_date or ref_date
        if r.start_date is None:
            continue
        tenure_days = (end - r.start_date).days
        if tenure_days > 0:
            tenures.append(tenure_days / 365.25)

    if not tenures:
        return None

    avg_tenure = float(np.mean(tenures))
    if avg_tenure <= 0:
        return 0.0
    score = avg_tenure / 5.0 if avg_tenure <= 5 else 1.0

    # Penalty for excessive manager count
    if len(current) > 3:
        score *= 0.8
    elif len(current) > 2:
        score *= 0.9

    return score


# ---------------------------------------------------------------------------
# holder — composite of institutional concentration, holder count, and
# employee co-investment (all higher → better within reasonable bounds)
# ---------------------------------------------------------------------------


def compute_holder(db: Session, fund_code: str, as_of_date: date | None = None) -> float | None:
    """Holder structure composite score.

    When ``as_of_date`` is provided, only holder structures with
    ``report_date <= as_of_date`` are considered.
    """
    stmt = select(HolderStructure).where(HolderStructure.fund_code == fund_code)
    if as_of_date is not None:
        stmt = stmt.where(HolderStructure.report_date <= as_of_date)
    stmt = stmt.order_by(HolderStructure.report_date.desc()).limit(1)

    row = db.scalar(stmt)
    if row is None:
        return None

    score = 0.5

    inst = row.institutional_pct or 0.0
    if 20 <= inst <= 60:
        score += 0.2
    elif inst > 80:
        score -= 0.3

    # total_holders may be None when the data source (East Money cyrjg endpoint)
    # does not provide holder count — in that case apply neutral treatment
    # (no bonus, no penalty) rather than defaulting to 0 which triggers <200 penalty.
    if row.total_holders is not None:
        holders = int(row.total_holders)
        if holders >= 10_000:
            score += 0.2
        elif holders >= 1_000:
            score += 0.1
        elif holders < 200:
            score -= 0.2

    emp = row.employee_pct or 0.0
    if emp > 0.5:
        score += 0.1

    return max(0.0, min(1.0, score))
