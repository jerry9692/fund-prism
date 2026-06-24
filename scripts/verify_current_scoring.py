"""Verify current-time 8-dimension coverage and scoring.

The backfill added scale/team/alpha data with report_date=2026-03-31.
For historical backtests these are invisible (as_of_date filtering
prevents lookahead bias), but for current scoring (as_of_date=today)
all 8 dimensions should now have data.

This script:
1. Verifies per-dimension coverage at the current date
2. Runs a single-point scoring at the current date
3. Confirms the 8-dimension composite score works end-to-end

Usage:
    .venv\\Scripts\\python.exe scripts\\verify_current_scoring.py
"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.analysis.nav_metrics import calculate_nav_metrics
from fund_research.analysis.scoring import ALGORITHM_VERSION, score_funds
from fund_research.analysis.scoring_dimensions import (
    compute_alpha,
    compute_holder,
    compute_scale,
    compute_style_stability,
    compute_team,
    compute_trading,
)
from fund_research.db.models import FundNAV
from fund_research.db.session import get_engine
from fund_research.experiments.runner import (
    _composite_risk_score,
    _safe_sharpe,
    _sample_years_from_nav,
)

SAMPLE_FUNDS = [
    "000001", "020005", "070002", "110009", "163406", "260108", "519068",
    "002939", "005827", "161005", "166002", "450002", "519736", "000697",
    "001071", "001938", "003095", "004851", "005267", "006228", "110022",
    "340007", "519712", "540003", "570001", "000409", "001480", "519772",
    "000978", "001810",
]

DIMENSIONS = [
    "return", "risk", "alpha", "trading",
    "style_stability", "scale", "team", "holder",
]


def main() -> None:
    engine = get_engine()
    scoring_date = date.today()
    print(f"Scoring date: {scoring_date}")
    print(f"Sample funds: {len(SAMPLE_FUNDS)}")
    print()

    metrics_rows: list[dict] = []
    sample_years: dict[str, float] = {}
    dimension_coverage: dict[str, int] = {d: 0 for d in DIMENSIONS}

    with Session(engine) as db:
        for fund_code in SAMPLE_FUNDS:
            nav_rows = db.scalars(
                select(FundNAV)
                .where(FundNAV.fund_code == fund_code)
                .order_by(FundNAV.trade_date)
            ).all()
            if not nav_rows:
                continue

            nav_df = pd.DataFrame([
                {
                    "trade_date": row.trade_date,
                    "unit_nav": row.unit_nav,
                    "daily_return": row.daily_return,
                }
                for row in nav_rows
            ])
            history_df = nav_df[pd.to_datetime(nav_df["trade_date"]).dt.date <= scoring_date]
            if history_df.empty:
                history_df = nav_df

            nav_metrics = calculate_nav_metrics(history_df)
            if not nav_metrics.metrics:
                continue

            sample_years[fund_code] = _sample_years_from_nav(nav_rows)

            row = {
                "fund_code": fund_code,
                "return": _safe_sharpe(nav_metrics.metrics),
                "risk": _composite_risk_score(nav_metrics.metrics),
                "alpha": compute_alpha(db, fund_code, as_of_date=scoring_date),
                "trading": compute_trading(db, fund_code, as_of_date=scoring_date),
                "style_stability": compute_style_stability(db, fund_code, as_of_date=scoring_date),
                "scale": compute_scale(db, fund_code, as_of_date=scoring_date),
                "team": compute_team(db, fund_code, as_of_date=scoring_date),
                "holder": compute_holder(db, fund_code, as_of_date=scoring_date),
            }
            metrics_rows.append(row)

            for dim in DIMENSIONS:
                if row[dim] is not None:
                    dimension_coverage[dim] += 1

    if not metrics_rows:
        print("No data collected")
        return

    print("=== Per-dimension coverage (current date) ===")
    total = len(metrics_rows)
    for dim in DIMENSIONS:
        count = dimension_coverage[dim]
        pct = count / total * 100 if total else 0
        status = "✓" if count > 0 else "✗"
        print(f"  {status} {dim:<20s}: {count}/{total} ({pct:.0f}%)")

    # Run scoring
    print(f"\n=== Running 8-dimension scoring v{ALGORITHM_VERSION} ===")
    scoring = score_funds(
        pd.DataFrame(metrics_rows),
        preset="均衡型",
        category="混合型-偏股",
        contains_estimated={"trading"},
        allow_estimated=True,
        sample_years_map=sample_years,
    )

    print(f"Score version: {scoring.score_version}")
    print(f"Fund count: {scoring.fund_count}")
    print(f"Warnings: {scoring.warnings}")
    print(f"Effective weights: {json.dumps(scoring.weight_config, indent=2)}")

    print("\n=== Top 5 funds ===")
    for fs in scoring.fund_scores[:5]:
        print(f"  {fs.fund_code}: score={fs.total_score:.2f} percentile={fs.percentile_rank:.4f}")
        print(f"    sub_scores: {json.dumps(fs.sub_scores, ensure_ascii=False)}")
        if fs.deduction_reasons:
            print(f"    deductions: {fs.deduction_reasons}")

    print("\n=== Bottom 5 funds ===")
    for fs in scoring.fund_scores[-5:]:
        print(f"  {fs.fund_code}: score={fs.total_score:.2f} percentile={fs.percentile_rank:.4f}")

    # Summary
    active_dims = sum(1 for d in DIMENSIONS if dimension_coverage[d] > 0)
    print("\n=== Summary ===")
    print(f"Active dimensions: {active_dims}/8")
    print(f"Total funds scored: {len(scoring.fund_scores)}")
    if scoring.warnings:
        print(f"Warnings: {len(scoring.warnings)}")
        for w in scoring.warnings:
            print(f"  - {w}")


if __name__ == "__main__":
    main()
