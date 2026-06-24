"""Check per-eval-date IC to see if later dates (with style_stability) improve."""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from scipy import stats
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


def _safe_sharpe(metrics):
    ann_ret = metrics.get("annualized_return")
    mdd = metrics.get("max_drawdown")
    if ann_ret is not None and mdd is not None:
        try:
            ann_ret_f = float(ann_ret)
            mdd_f = float(mdd)
        except (TypeError, ValueError):
            pass
        else:
            if mdd_f < 0:
                return ann_ret_f / abs(mdd_f)
            if mdd_f == 0 and ann_ret_f > 0:
                return ann_ret_f * 10.0
    if ann_ret is not None:
        try:
            return float(ann_ret)
        except (TypeError, ValueError):
            pass
    return None


def _risk_score(metrics):
    vol = float(metrics.get("annualized_volatility") or 0)
    mdd = float(metrics.get("max_drawdown") or 0)
    return -(vol + abs(mdd)) / 2.0


def main() -> None:
    fund_codes = load_sample_funds()
    engine = get_engine()

    with Session(engine) as db:
        for eval_date in EVAL_DATES:
            forward_end = eval_date + timedelta(days=365)
            rows = []
            forward_returns = {}

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

                # Forward return
                fwd_rows = db.scalars(
                    select(FundNAV)
                    .where(FundNAV.fund_code == code)
                    .where(FundNAV.trade_date > eval_date)
                    .where(FundNAV.trade_date <= forward_end)
                    .order_by(FundNAV.trade_date)
                ).all()
                if len(fwd_rows) >= 60:
                    start_nav = float(fwd_rows[0].unit_nav)
                    end_nav = float(fwd_rows[-1].unit_nav)
                    forward_returns[code] = (end_nav / start_nav) - 1.0

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
                continue

            df = pd.DataFrame(rows).set_index("fund_code")
            result = score_funds(df.reset_index(), weights=DEFAULT_WEIGHTS)

            # Compute IC for this date
            scores = []
            returns = []
            for fs in result.fund_scores:
                if fs.fund_code in forward_returns:
                    scores.append(fs.total_score)
                    returns.append(forward_returns[fs.fund_code])

            if len(scores) >= 5:
                ic, p_value = stats.spearmanr(scores, returns)
                non_null_dims = sum(1 for col in df.columns if df[col].notna().any())
                print(
                    f"{eval_date}: IC={ic:.4f} p={p_value:.4f} "
                    f"funds={len(scores)} dims={non_null_dims}/8 "
                    f"eff_weights={ {k: round(v, 2) for k, v in result.weight_config.items()} }"
                )
            else:
                print(f"{eval_date}: insufficient data ({len(scores)} funds)")


if __name__ == "__main__":
    main()
