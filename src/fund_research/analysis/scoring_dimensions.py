"""
Real-data extraction for the 6 scoring dimensions beyond return/risk.

Each function accepts a DB session and fund_code, and returns a float
(or None when data is unavailable).  All values are oriented so that
"higher = better" — the scoring pipeline handles Z-score / percentile
standardisation downstream.
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


def compute_alpha(db: Session, fund_code: str) -> float | None:
    row = db.scalar(
        select(StaticAttributionResult)
        .where(StaticAttributionResult.fund_code == fund_code)
        .order_by(StaticAttributionResult.report_date.desc())
        .limit(1)
    )
    if row is None:
        return None
    sel = row.selection_effect or 0.0
    alloc = row.allocation_effect or 0.0
    return sel + alloc


# ---------------------------------------------------------------------------
# trading — turnover estimated from consecutive semi-annual disclosures
# (lower turnover → higher score, so we negate)
# ---------------------------------------------------------------------------


def compute_trading(db: Session, fund_code: str) -> float | None:
    rows = db.scalars(
        select(FundDisclosedHoldings)
        .where(FundDisclosedHoldings.fund_code == fund_code)
        .where(FundDisclosedHoldings.asset_type == "股票")
        .order_by(FundDisclosedHoldings.report_date.desc())
        .limit(300)
    ).all()
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


def compute_style_stability(db: Session, fund_code: str) -> float | None:
    rows = db.scalars(
        select(StyleExposureResult)
        .where(StyleExposureResult.fund_code == fund_code)
        .where(StyleExposureResult.exposure_type == "style")
        .order_by(StyleExposureResult.calc_date.desc())
        .limit(12)
    ).all()
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

_LOG_10_E = 4.342944819032518  # 10/ln(10) ≈ 4.3429 (not used currently)


def compute_scale(db: Session, fund_code: str) -> float | None:
    rows = db.scalars(
        select(FundScale)
        .where(FundScale.fund_code == fund_code)
        .order_by(FundScale.report_date.desc())
        .limit(1)
    ).all()
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


def compute_team(db: Session, fund_code: str) -> float | None:
    rows = db.scalars(
        select(FundManagerTenure)
        .where(FundManagerTenure.fund_code == fund_code)
        .order_by(FundManagerTenure.start_date.desc())
    ).all()
    if not rows:
        return None

    current = [r for r in rows if r.is_current]
    if not current:
        return None

    tenures = [
        r.tenure_days / 365.25
        for r in current
        if r.tenure_days and r.tenure_days > 0
    ]
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


def compute_holder(db: Session, fund_code: str) -> float | None:
    row = db.scalar(
        select(HolderStructure)
        .where(HolderStructure.fund_code == fund_code)
        .order_by(HolderStructure.report_date.desc())
        .limit(1)
    )
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
