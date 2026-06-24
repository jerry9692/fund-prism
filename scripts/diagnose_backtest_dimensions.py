"""Deep diagnosis of scoring backtest: inspect per-eval-date dimension coverage
and effective weights after redistribution."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.analysis.nav_metrics import calculate_nav_metrics
from fund_research.analysis.scoring import DEFAULT_WEIGHTS, score_funds
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

SAMPLE_FUNDS_PATH = Path("data/samples/sample_funds_v0.1.csv")
EVAL_DATES = [
    date(2024, 3, 31),
    date(2024, 6, 30),
    date(2024, 9, 30),
    date(2024, 12, 31),
    date(2025, 3, 31),
]


def load_sample_funds() -> list[str]:
    with SAMPLE_FUNDS_PATH.open(encoding="utf-8") as f:
        return [row["fund_code"] for row in csv.DictReader(f)]


def main() -> None:
    fund_codes = load_sample_funds()
    engine = get_engine()

    with Session(engine) as db:
        for eval_date in EVAL_DATES:
            print(f"\n=== Eval date: {eval_date} ===")
            rows = []
            for code in fund_codes:
                nav_rows = db.scalars(
                    select(FundNAV)
                    .where(FundNAV.fund_code == code)
                    .where(FundNAV.trade_date <= eval_date)
                    .order_by(FundNAV.trade_date)
                ).all()
                if len(nav_rows) < 504:
                    continue

                nav_df = pd.DataFrame([
                    {
                        "trade_date": r.trade_date,
                        "unit_nav": r.unit_nav,
                        "daily_return": r.daily_return,
                    }
                    for r in nav_rows
                ])
                nav_metrics = calculate_nav_metrics(nav_df)

                def _safe_sharpe(metrics):
                    s = metrics.get("sharpe_ratio")
                    if s is not None:
                        return float(s)
                    ar = metrics.get("annualized_return")
                    av = metrics.get("annualized_volatility")
                    if ar is None or av is None or float(av) <= 0:
                        return None
                    return float(ar) / float(av)

                def _risk_score(metrics):
                    vol = float(metrics.get("annualized_volatility") or 0)
                    mdd = float(metrics.get("max_drawdown") or 0)
                    return -(vol + abs(mdd)) / 2.0

                rows.append({
                    "fund_code": code,
                    "return": _safe_sharpe(nav_metrics.metrics),
                    "risk": _risk_score(nav_metrics.metrics),
                    "alpha": compute_alpha(db, code, as_of_date=eval_date),
                    "trading": compute_trading(db, code, as_of_date=eval_date),
                    "style_stability": compute_style_stability(db, code, as_of_date=eval_date),
                    "scale": compute_scale(db, code, as_of_date=eval_date),
                    "team": compute_team(db, code, as_of_date=eval_date),
                    "holder": compute_holder(db, code, as_of_date=eval_date),
                })

            if not rows:
                print("  No funds with sufficient NAV history")
                continue

            df = pd.DataFrame(rows).set_index("fund_code")
            print(f"  Funds: {len(df)}")

            # Dimension coverage
            print("  Dimension coverage (non-null count):")
            for col in df.columns:
                non_null = df[col].notna().sum()
                print(f"    {col:20s}: {non_null}/{len(df)}")

            # Run score_funds and check effective weights
            result = score_funds(df.reset_index(), weights=DEFAULT_WEIGHTS)
            print(f"\n  Effective weights: {result.weight_config}")
            print(f"  Warnings: {result.warnings}")

            # Show top 5 and bottom 5 scores
            sorted_scores = sorted(result.fund_scores, key=lambda x: x.total_score, reverse=True)
            print("\n  Top 5:")
            for fs in sorted_scores[:5]:
                print(f"    {fs.fund_code}: {fs.total_score:.2f}  subs={fs.sub_scores}")
            print("  Bottom 5:")
            for fs in sorted_scores[-5:]:
                print(f"    {fs.fund_code}: {fs.total_score:.2f}  subs={fs.sub_scores}")


if __name__ == "__main__":
    main()
