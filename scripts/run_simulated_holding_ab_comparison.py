"""Run A/B comparison of optimized vs naive simulated holding on 30 funds.

Creates two simulated_holding experiments (one per method), dispatches both,
then produces a side-by-side comparison of:
- success / failure count and taxonomy
- tracking error distribution
- Top10 recall and industry correlation
- matched stock count and return sample count

Usage:
    .venv\\Scripts\\python.exe scripts\\run_simulated_holding_ab_comparison.py
"""

from __future__ import annotations

import json
import statistics
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.db.models import ExperimentResult
from fund_research.db.session import get_engine
from fund_research.experiments.manager import create_experiment
from fund_research.experiments.runner import dispatch_run

SAMPLE_FUNDS = [
    "000001", "020005", "070002", "110009", "163406", "260108", "519068",
    "002939", "005827", "161005", "166002", "450002", "519736", "000697",
    "001071", "001938", "003095", "004851", "005267", "006228", "110022",
    "340007", "519712", "540003", "570001", "000409", "001480", "519772",
    "000978", "001810",
]


def _classify_failure(error_message: str | None) -> str:
    if not error_message:
        return "unknown"
    if "无净值" in error_message:
        return "no_nav_data"
    if "无持仓" in error_message:
        return "no_holdings_data"
    if "无股票" in error_message:
        return "no_stock_data"
    if "无可用周期" in error_message:
        return "no_overlap_period"
    if "收益样本不足" in error_message:
        return "insufficient_return_samples"
    if "跟踪误差偏高" in error_message:
        return "high_tracking_error"
    return f"other:{error_message[:60]}"


def _run_method(db: Session, method: str) -> tuple[int, list[dict], Counter]:
    """Run one method on all 30 funds and return (experiment_id, details, failure_taxonomy)."""
    exp = create_experiment(
        db,
        experiment_name=f"P2 simulated_holding A/B 30-fund ({method})",
        algorithm_name="simulated_holding",
        algorithm_version="0.1.0",
        parameters={
            "method": method,
            "max_positions": 20,
            "window_days": 60,
            "max_single_weight": 0.10,
            "turnover_penalty": 0.5,
            "industry_penalty": 0.5,
        },
        sample_fund_codes=SAMPLE_FUNDS,
    )
    print(f"\n[{method}] Created experiment id={exp.id}")
    results = dispatch_run(db, exp)
    db.commit()

    success = sum(1 for r in results if r.get("is_success"))
    print(f"[{method}] Run complete: {success}/{len(results)} succeeded")

    exp_results = db.scalars(
        select(ExperimentResult).where(ExperimentResult.experiment_id == exp.id)
    ).all()

    details: list[dict] = []
    taxonomy: Counter[str] = Counter()
    for r in exp_results:
        metrics = r.metrics or {}
        entry = {
            "fund_code": r.fund_code,
            "is_success": r.is_success,
            "tracking_error": metrics.get("estimated_overall_tracking_error"),
            "top10_recall": metrics.get("estimated_overall_top10_recall"),
            "industry_corr": metrics.get("estimated_overall_industry_correlation"),
            "matched_stocks": metrics.get("matched_stock_count"),
            "return_samples": metrics.get("return_sample_count"),
            "method": metrics.get("method"),
            "error": r.error_message,
        }
        details.append(entry)
        if not r.is_success:
            taxonomy[_classify_failure(r.error_message)] += 1

    return exp.id, details, taxonomy


def _stats(values: list[float | None]) -> dict:
    valid = [v for v in values if v is not None]
    if not valid:
        return {"count": 0, "mean": None, "median": None, "min": None, "max": None}
    valid.sort()
    return {
        "count": len(valid),
        "mean": round(statistics.mean(valid), 6),
        "median": round(statistics.median(valid), 6),
        "min": round(valid[0], 6),
        "max": round(valid[-1], 6),
    }


def _print_comparison(opt_details: list[dict], naive_details: list[dict]) -> None:
    """Print side-by-side comparison table."""
    opt_map = {d["fund_code"]: d for d in opt_details}
    naive_map = {d["fund_code"]: d for d in naive_details}

    print("\n" + "=" * 100)
    print("A/B Comparison: optimized (CVXPY/SciPy) vs naive (disclosed-weight replication)")
    print("=" * 100)

    header = (
        f"{'fund':8s} | {'opt_succ':>8s} {'opt_TE':>10s} {'opt_rcl':>8s} {'opt_ind':>8s}"
        f" | {'nai_succ':>8s} {'nai_TE':>10s} {'nai_rcl':>8s} {'nai_ind':>8s}"
        f" | {'TE_diff':>10s}"
    )
    print(header)
    print("-" * len(header))

    for fund in SAMPLE_FUNDS:
        o = opt_map.get(fund, {})
        n = naive_map.get(fund, {})
        o_te = o.get("tracking_error")
        n_te = n.get("tracking_error")
        te_diff = None
        if o_te is not None and n_te is not None:
            te_diff = o_te - n_te

        def _fmt(v, fmt=".4f"):
            if v is None:
                return "N/A"
            return f"{v:{fmt}}"

        o_succ = "Y" if o.get("is_success") else "N"
        n_succ = "Y" if n.get("is_success") else "N"
        print(
            f"{fund:8s} | "
            f"{o_succ:>8s} {_fmt(o_te):>10s} {_fmt(o.get('top10_recall')):>8s} "
            f"{_fmt(o.get('industry_corr')):>8s}"
            f" | "
            f"{n_succ:>8s} {_fmt(n_te):>10s} {_fmt(n.get('top10_recall')):>8s} "
            f"{_fmt(n.get('industry_corr')):>8s}"
            f" | {_fmt(te_diff):>10s}"
        )

    # Aggregate stats
    opt_success = [d for d in opt_details if d["is_success"]]
    naive_success = [d for d in naive_details if d["is_success"]]

    print("\n=== Aggregate Stats (successful funds only) ===")
    print(f"{'metric':25s} | {'optimized':>20s} | {'naive':>20s}")
    print("-" * 70)
    for label, key in [
        ("success count", None),
        ("tracking_error", "tracking_error"),
        ("top10_recall", "top10_recall"),
        ("industry_correlation", "industry_corr"),
        ("matched_stocks", "matched_stocks"),
        ("return_samples", "return_samples"),
    ]:
        if key is None:
            print(f"{label:25s} | {len(opt_success):>20d} | {len(naive_success):>20d}")
        else:
            o_stats = _stats([d[key] for d in opt_success])
            n_stats = _stats([d[key] for d in naive_success])
            print(
                f"{label:25s} | "
                f"mean={o_stats['mean']}, n={o_stats['count']:>2d} | "
                f"mean={n_stats['mean']}, n={n_stats['count']:>2d}"
            )


def main() -> None:
    engine = get_engine()
    with Session(engine) as db:
        # Run both methods
        _, opt_details, opt_taxonomy = _run_method(db, "optimized")
        _, naive_details, naive_taxonomy = _run_method(db, "naive")

        # Print comparison
        _print_comparison(opt_details, naive_details)

        # Failure taxonomy
        print("\n=== Failure Taxonomy ===")
        print(f"{'reason':40s} | {'optimized':>10s} | {'naive':>10s}")
        print("-" * 65)
        all_reasons = set(opt_taxonomy.keys()) | set(naive_taxonomy.keys())
        for reason in sorted(all_reasons):
            print(f"{reason:40s} | {opt_taxonomy.get(reason, 0):>10d} | {naive_taxonomy.get(reason, 0):>10d}")

        # Summary JSON
        opt_success = [d for d in opt_details if d["is_success"]]
        naive_success = [d for d in naive_details if d["is_success"]]
        summary = {
            "sample_size": len(SAMPLE_FUNDS),
            "optimized": {
                "success_count": len(opt_success),
                "failure_count": len(opt_details) - len(opt_success),
                "failure_taxonomy": dict(opt_taxonomy),
                "te_stats": _stats([d["tracking_error"] for d in opt_success]),
                "recall_stats": _stats([d["top10_recall"] for d in opt_success]),
                "industry_stats": _stats([d["industry_corr"] for d in opt_success]),
            },
            "naive": {
                "success_count": len(naive_success),
                "failure_count": len(naive_details) - len(naive_success),
                "failure_taxonomy": dict(naive_taxonomy),
                "te_stats": _stats([d["tracking_error"] for d in naive_success]),
                "recall_stats": _stats([d["top10_recall"] for d in naive_success]),
                "industry_stats": _stats([d["industry_corr"] for d in naive_success]),
            },
        }
        print("\n=== Summary JSON ===")
        print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
