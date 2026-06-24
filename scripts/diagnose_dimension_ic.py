"""Diagnose per-dimension IC to find which dimensions are inverted.

Computes the Spearman correlation between each raw scoring dimension
and the forward 12-month return, across all eval dates in the 2021-2025
backtest window. A negative correlation means the dimension is an
inverted signal in the A-share market and its direction (or weight)
needs adjustment.

Usage:
    .venv\\Scripts\\python.exe scripts\\diagnose_dimension_ic.py
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.analysis.nav_metrics import calculate_nav_metrics
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
    _MIN_LOOKBACK_DAYS,
    _add_months,
    _composite_risk_score,
    _forward_nav_metrics,
    _quarterly_dates,
    _safe_sharpe,
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
    eval_dates = _quarterly_dates(date(2021, 3, 31), date(2025, 3, 31))
    forward_months = 12
    min_forward_observations = 60

    print(f"Eval dates: {len(eval_dates)} ({eval_dates[0]} to {eval_dates[-1]})")
    print(f"Sample funds: {len(SAMPLE_FUNDS)}")
    print()

    all_rows: list[dict] = []

    with Session(engine) as db:
        for eval_date in eval_dates:
            forward_end = _add_months(eval_date, forward_months)
            period_rows: list[dict] = []

            for fund_code in SAMPLE_FUNDS:
                try:
                    nav_rows = db.scalars(
                        select(FundNAV)
                        .where(FundNAV.fund_code == fund_code)
                        .where(FundNAV.trade_date <= eval_date)
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
                    nav_df["trade_date"] = pd.to_datetime(nav_df["trade_date"])
                    nav_df = nav_df.sort_values("trade_date")

                    lookback_start = eval_date - timedelta(days=_MIN_LOOKBACK_DAYS)
                    window_df = nav_df[nav_df["trade_date"] >= pd.Timestamp(lookback_start)]
                    if len(window_df) < 60:
                        continue

                    nav_metrics = calculate_nav_metrics(window_df)
                    if not nav_metrics.metrics:
                        continue

                    future_nav = db.scalars(
                        select(FundNAV)
                        .where(FundNAV.fund_code == fund_code)
                        .where(FundNAV.trade_date > eval_date)
                        .where(FundNAV.trade_date <= forward_end)
                        .order_by(FundNAV.trade_date)
                    ).all()
                    forward_metrics = _forward_nav_metrics(future_nav)
                    if forward_metrics["observation_count"] < min_forward_observations:
                        continue

                    row = {
                        "fund_code": fund_code,
                        "eval_date": str(eval_date),
                        "future_return": forward_metrics["future_return"],
                        "return": _safe_sharpe(nav_metrics.metrics),
                        "risk": _composite_risk_score(nav_metrics.metrics),
                        "alpha": compute_alpha(db, fund_code, as_of_date=eval_date),
                        "trading": compute_trading(db, fund_code, as_of_date=eval_date),
                        "style_stability": compute_style_stability(db, fund_code, as_of_date=eval_date),
                        "scale": compute_scale(db, fund_code, as_of_date=eval_date),
                        "team": compute_team(db, fund_code, as_of_date=eval_date),
                        "holder": compute_holder(db, fund_code, as_of_date=eval_date),
                    }
                    period_rows.append(row)
                    all_rows.append(row)
                except Exception as exc:
                    print(f"  {fund_code} @ {eval_date}: ERROR {exc}")
                    continue

            if period_rows:
                print(f"  {eval_date}: {len(period_rows)} funds with data")

    if not all_rows:
        print("No data collected")
        return

    df = pd.DataFrame(all_rows)
    print(f"\n=== Total observations: {len(df)} ===")
    print(f"Eval dates with data: {df['eval_date'].nunique()}")
    print(f"Funds with data: {df['fund_code'].nunique()}")

    print("\n=== Per-dimension diagnostics ===")
    print(f"{'dimension':<20s} {'coverage':>10s} {'mean_ic':>10s} {'std_ic':>10s} {'pct_negative':>14s}")
    print("-" * 70)

    dimension_ic_summary: dict[str, dict] = {}
    for dim in DIMENSIONS:
        # Per-date Spearman IC
        ics: list[float] = []
        for _eval_date, group in df.groupby("eval_date"):
            valid = group[[dim, "future_return"]].dropna()
            if len(valid) < 5:
                continue
            if valid[dim].nunique() < 2:
                continue
            ic = valid[dim].corr(valid["future_return"], method="spearman")
            if pd.notna(ic):
                ics.append(float(ic))

        if not ics:
            coverage = df[dim].notna().sum()
            print(f"{dim:<20s} {coverage:>10d} {'N/A':>10s} {'N/A':>10s} {'N/A':>14s}")
            continue

        ic_series = pd.Series(ics)
        coverage = df[dim].notna().sum()
        pct_negative = float((ic_series < 0).mean())
        print(
            f"{dim:<20s} {coverage:>10d} {ic_series.mean():>10.4f} "
            f"{ic_series.std():>10.4f} {pct_negative:>14.1%}"
        )
        dimension_ic_summary[dim] = {
            "coverage": int(coverage),
            "coverage_pct": round(float(df[dim].notna().mean()), 4),
            "mean_ic": round(float(ic_series.mean()), 6),
            "std_ic": round(float(ic_series.std()), 6),
            "ic_ir": round(float(ic_series.mean() / ic_series.std()), 4)
            if ic_series.std() > 0 else None,
            "pct_negative": round(pct_negative, 4),
            "ic_count": len(ics),
        }

    # Also compute the pooled Spearman IC (all observations together)
    print("\n=== Pooled Spearman IC (all observations) ===")
    pooled_ics: dict[str, float] = {}
    for dim in DIMENSIONS:
        valid = df[[dim, "future_return"]].dropna()
        if len(valid) < 10 or valid[dim].nunique() < 2:
            pooled_ics[dim] = float("nan")
            continue
        ic = valid[dim].corr(valid["future_return"], method="spearman")
        pooled_ics[dim] = float(ic)
        print(f"  {dim:<20s}: {ic:>8.4f}  (n={len(valid)})")

    # Save full report
    report = {
        "total_observations": len(df),
        "eval_dates": int(df["eval_date"].nunique()),
        "funds": int(df["fund_code"].nunique()),
        "dimension_ic_summary": dimension_ic_summary,
        "pooled_ic": {k: round(v, 6) for k, v in pooled_ics.items() if not np.isnan(v)},
    }
    print("\n=== Full report (JSON) ===")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
