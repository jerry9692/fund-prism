"""Full-dimension scoring backtest for 30 sample funds (2021-2025).

Uses all 8 scoring dimensions with historical team/holder data now available.
Runs quarterly evaluation from 2021-06-30 to 2024-12-31.
"""
import csv
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import select as sa_select
from sqlalchemy.orm import sessionmaker

from fund_research.analysis.scoring import (
    ALGORITHM_VERSION,
    DEFAULT_WEIGHTS,
    compute_scoring_backtest,
    score_funds,
)
from fund_research.config.settings import get_settings
from fund_research.db.models import FundNAV
from fund_research.db.session import create_engine_from_path, init_db
from fund_research.experiments.runner import (
    _add_months,
    _composite_risk_score,
    _DEFAULT_MIN_FORWARD_OBSERVATIONS,
    _forward_nav_metrics,
    _MIN_LOOKBACK_DAYS,
    _quarterly_dates,
    _safe_sharpe,
    _sample_years_from_nav,
)
from fund_research.analysis.scoring_dimensions import (
    compute_alpha,
    compute_holder,
    compute_scale,
    compute_style_stability,
    compute_team,
    compute_trading,
)


def main() -> None:
    settings = get_settings()
    sample_path = settings.sample_funds_path_absolute
    db_path = settings.db_path_absolute
    print(f"Database: {db_path}")
    print(f"Sample funds: {sample_path}")

    init_db(db_path)
    engine = create_engine_from_path(db_path)
    Session = sessionmaker(bind=engine)

    fund_codes: list[str] = []
    with open(sample_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            code = row.get("fund_code", "").strip()
            if code:
                fund_codes.append(code)
    fund_codes = sorted(set(fund_codes))
    print(f"Sample funds: {len(fund_codes)}")

    eval_start = date(2021, 6, 30)
    eval_end = date(2024, 12, 31)
    forward_months = 3
    eval_dates = _quarterly_dates(eval_start, eval_end)
    print(f"Eval dates ({len(eval_dates)}): {[str(d) for d in eval_dates]}")

    scores_rows: list[dict] = []
    future_rows: list[dict] = []
    dimension_coverage: dict[str, list] = {d: [] for d in DEFAULT_WEIGHTS}

    for eval_date in eval_dates:
        forward_end = _add_months(eval_date, forward_months)
        period_metrics: list[dict] = []
        period_years: dict[str, float] = {}
        dim_count = {d: 0 for d in DEFAULT_WEIGHTS}

        with Session() as db:
            for fund_code in fund_codes:
                nav_rows = db.scalars(
                    sa_select(FundNAV)
                    .where(FundNAV.fund_code == fund_code)
                    .where(FundNAV.trade_date <= eval_date)
                    .order_by(FundNAV.trade_date)
                ).all()
                if not nav_rows:
                    continue

                nav_df = pd.DataFrame([
                    {"trade_date": r.trade_date, "unit_nav": r.unit_nav, "daily_return": r.daily_return}
                    for r in nav_rows
                ])
                nav_df["trade_date"] = pd.to_datetime(nav_df["trade_date"])
                nav_df = nav_df.sort_values("trade_date")

                lookback_start = eval_date - timedelta(days=_MIN_LOOKBACK_DAYS)
                window_df = nav_df[nav_df["trade_date"] >= pd.Timestamp(lookback_start)]
                if len(window_df) < 60:
                    continue

                from fund_research.analysis.nav_metrics import calculate_nav_metrics
                nav_metrics = calculate_nav_metrics(window_df)
                if not nav_metrics.metrics:
                    continue

                future_nav = db.scalars(
                    sa_select(FundNAV)
                    .where(FundNAV.fund_code == fund_code)
                    .where(FundNAV.trade_date > eval_date)
                    .where(FundNAV.trade_date <= forward_end)
                    .order_by(FundNAV.trade_date)
                ).all()
                fwd = _forward_nav_metrics(list(future_nav))
                min_fwd = 20
                if fwd["observation_count"] < min_fwd:
                    continue

                period_years[fund_code] = _sample_years_from_nav(nav_rows)

                ret_val = _safe_sharpe(nav_metrics.metrics)
                risk_val = _composite_risk_score(nav_metrics.metrics)
                alpha_val = compute_alpha(db, fund_code, as_of_date=eval_date)
                trading_val = compute_trading(db, fund_code, as_of_date=eval_date)
                style_val = compute_style_stability(db, fund_code, as_of_date=eval_date)
                scale_val = compute_scale(db, fund_code, as_of_date=eval_date)
                team_val = compute_team(db, fund_code, as_of_date=eval_date)
                holder_val = compute_holder(db, fund_code, as_of_date=eval_date)

                dim_values = {
                    "return": ret_val, "risk": risk_val, "alpha": alpha_val,
                    "trading": trading_val, "style_stability": style_val,
                    "scale": scale_val, "team": team_val, "holder": holder_val,
                }
                for d, v in dim_values.items():
                    if v is not None and not pd.isna(v):
                        dim_count[d] += 1

                period_metrics.append({"fund_code": fund_code, **dim_values})
                future_rows.append({
                    "fund_code": fund_code,
                    "calc_date": eval_date,
                    **fwd,
                })

        n = len(period_metrics)
        print(f"\n--- {eval_date}: {n} funds ---")
        for d in DEFAULT_WEIGHTS:
            cov = dim_count[d] / n if n > 0 else 0
            dimension_coverage[d].append(cov)
            print(f"  {d:20s}: {dim_count[d]}/{n} ({cov:.0%})")

        if n < 5:
            print(f"  SKIP (need >=5 funds)")
            continue

        scoring = score_funds(
            pd.DataFrame(period_metrics),
            weights=DEFAULT_WEIGHTS,
            preset=None,
            category="混合型-偏股",
            contains_estimated={"trading"},
            allow_estimated=True,
            sample_years_map=period_years,
        )
        for fs in scoring.fund_scores:
            scores_rows.append({
                "fund_code": fs.fund_code,
                "calc_date": eval_date,
                "score": fs.total_score,
            })
        if scoring.warnings:
            for w in scoring.warnings:
                print(f"  WARN: {w}")

    if not scores_rows:
        print("\nERROR: No scoring data generated!")
        return

    scores_df = pd.DataFrame(scores_rows)
    future_df = pd.DataFrame(future_rows)
    print(f"\n\n{'='*60}")
    print(f"FULL-DIMENSION BACKTEST RESULTS (8 dimensions with team+holder)")
    print(f"{'='*60}")
    print(f"Algorithm version: {ALGORITHM_VERSION}")
    print(f"Eval periods: {len(eval_dates)}")
    print(f"Total score observations: {len(scores_df)}")

    bt = compute_scoring_backtest(scores_df, future_df, group_count=5)
    print(f"\n--- IC Summary ---")
    print(f"  IC mean:              {bt['ic_mean']}")
    print(f"  IC IR:                {bt['ic_ir']}")
    print(f"  Sample count:         {bt['sample_count']}")
    print(f"  Monotonicity:         {bt['monotonicity']}")
    print(f"  Top-Bottom spread:    {bt['top_bottom_return_spread']}")
    print(f"  Top-Bottom p-value:   {bt['top_bottom_one_sided_p_value']}")

    print(f"\n--- Group Returns (5 quintiles, 0=worst, 4=best) ---")
    gr = bt.get("group_results", {})
    for bucket in sorted(gr.keys(), key=lambda x: int(x)):
        vals = gr[bucket]
        ret = vals.get("future_return")
        sharpe = vals.get("future_sharpe")
        dd = vals.get("future_max_drawdown")
        ret_str = f"{ret:.4f}" if ret is not None else "N/A"
        sharpe_str = f"{sharpe:.2f}" if sharpe is not None else "N/A"
        dd_str = f"{dd:.4f}" if dd is not None else "N/A"
        print(f"  Q{bucket}: return={ret_str}, sharpe={sharpe_str}, maxdd={dd_str}")

    mono = bt.get("monotonicity_by_metric", {})
    print(f"\n--- Monotonicity Checks ---")
    for metric, is_mono in mono.items():
        print(f"  {metric}: {'PASS' if is_mono else 'FAIL'}")

    print(f"\n--- Dimension Coverage (avg across periods) ---")
    for d in DEFAULT_WEIGHTS:
        vals = dimension_coverage[d]
        avg = sum(vals) / len(vals) if vals else 0
        w = DEFAULT_WEIGHTS[d]
        status = "OK" if avg > 0.8 else ("PARTIAL" if avg > 0.3 else "MISSING")
        print(f"  {d:20s}: weight={w:.2f}, avg_coverage={avg:.0%} [{status}]")

    latest_date = eval_dates[-1]
    latest_scores = [s for s in scores_rows if s["calc_date"] == latest_date]
    latest_scores.sort(key=lambda x: x["score"], reverse=True)
    print(f"\n--- Latest Scores ({latest_date}, top 10) ---")
    for i, s in enumerate(latest_scores[:10]):
        print(f"  #{i+1:2d}  {s['fund_code']}: {s['score']:.1f}")


if __name__ == "__main__":
    main()
