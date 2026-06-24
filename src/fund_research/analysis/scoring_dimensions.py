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
    """Selection + allocation effect from the latest static attribution.

    When ``as_of_date`` is provided, only attributions with
    ``report_date <= as_of_date`` are considered, preventing lookahead bias.
    """
    stmt = (
        select(StaticAttributionResult)
        .where(StaticAttributionResult.fund_code == fund_code)
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
# (lower turnover → higher score, so we negate)
# ---------------------------------------------------------------------------


def compute_trading(db: Session, fund_code: str, as_of_date: date | None = None) -> float | None:
    """Turnover estimated from the two most recent disclosed holding periods.

    When ``as_of_date`` is provided, only holdings with
    ``report_date <= as_of_date`` are considered.
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
    return -turnover


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

    holders = row.total_holders or 0
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
