"""Run simulated holding on all 30 sample funds and record failure taxonomy.

Creates a simulated_holding experiment, dispatches it, then summarises:
- success vs failure count
- failure reason taxonomy
- tracking error distribution
- matched stock count distribution
- confidence levels

Usage:
    .venv\\Scripts\\python.exe scripts\\run_simulated_holding_30funds.py
"""

from __future__ import annotations

import json
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.db.models import ExperimentResult, SimulatedHoldingResult
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
    """Map raw error messages to taxonomy categories."""
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


def main() -> None:
    engine = get_engine()
    with Session(engine) as db:
        exp = create_experiment(
            db,
            experiment_name="P2 simulated_holding 30-fund expansion (optimized)",
            algorithm_name="simulated_holding",
            algorithm_version="0.1.0",
            parameters={
                "method": "optimized",
                "max_positions": 20,
                "window_days": 60,
                "max_single_weight": 0.10,
                "turnover_penalty": 0.5,
                "industry_penalty": 0.5,
            },
            sample_fund_codes=SAMPLE_FUNDS,
        )
        print(f"Created experiment id={exp.id}")

        results = dispatch_run(db, exp)
        db.commit()

        success_count = sum(1 for r in results if r.get("is_success"))
        failure_count = len(results) - success_count
        print(f"\nRun complete: {success_count}/{len(results)} succeeded, {failure_count} failed")

        # Pull persisted results for taxonomy
        exp_results = db.scalars(
            select(ExperimentResult).where(ExperimentResult.experiment_id == exp.id)
        ).all()

        # Failure taxonomy
        failure_taxonomy: Counter[str] = Counter()
        success_details: list[dict] = []
        failure_details: list[dict] = []

        for r in exp_results:
            metrics = r.metrics or {}
            te = metrics.get("estimated_overall_tracking_error")
            matched = metrics.get("matched_stock_count")
            samples = metrics.get("return_sample_count")
            method = metrics.get("method")
            entry = {
                "fund_code": r.fund_code,
                "is_success": r.is_success,
                "tracking_error": te,
                "matched_stocks": matched,
                "return_samples": samples,
                "method": method,
                "error": r.error_message,
            }
            if r.is_success:
                success_details.append(entry)
            else:
                failure_details.append(entry)
                failure_taxonomy[_classify_failure(r.error_message)] += 1

        print("\n=== Failure Taxonomy ===")
        for reason, count in failure_taxonomy.most_common():
            print(f"  {reason:40s}: {count}")

        print("\n=== Success Details ===")
        print(f"{'fund':8s} {'TE':>8s} {'matched':>8s} {'samples':>8s} {'method':>20s}")
        for e in sorted(success_details, key=lambda x: x["tracking_error"] or 0):
            te_str = f"{e['tracking_error']:.4f}" if e["tracking_error"] is not None else "N/A"
            print(
                f"{e['fund_code']:8s} {te_str:>8s} "
                f"{e['matched_stocks'] or 0:>8d} {e['return_samples'] or 0:>8d} "
                f"{e['method'] or 'N/A':>20s}"
            )

        print("\n=== Failure Details ===")
        print(f"{'fund':8s} {'error':>60s}")
        for e in failure_details:
            print(f"{e['fund_code']:8s} {(e['error'] or '')[:60]:>60s}")

        # TE distribution
        tes = [e["tracking_error"] for e in success_details if e["tracking_error"] is not None]
        if tes:
            tes.sort()
            print("\n=== Tracking Error Distribution ===")
            print(f"  min:    {tes[0]:.4f}")
            print(f"  p25:    {tes[len(tes)//4]:.4f}")
            print(f"  median: {tes[len(tes)//2]:.4f}")
            print(f"  p75:    {tes[3*len(tes)//4]:.4f}")
            print(f"  max:    {tes[-1]:.4f}")
            print(f"  mean:   {sum(tes)/len(tes):.4f}")

        # Persisted SimulatedHoldingResult rows (query by fund codes + version)
        sim_rows = db.scalars(
            select(SimulatedHoldingResult)
            .where(SimulatedHoldingResult.fund_code.in_(SAMPLE_FUNDS))
            .where(SimulatedHoldingResult.algorithm_version == "0.1.0")
            .order_by(SimulatedHoldingResult.created_at.desc())
            .limit(30)
        ).all()
        print(f"\nPersisted SimulatedHoldingResult rows: {len(sim_rows)}")
        confidence_counts: Counter[str] = Counter()
        for sr in sim_rows:
            confidence_counts[sr.conclusion_status or "unknown"] += 1
        print(f"Confidence levels: {dict(confidence_counts)}")

        # Summary JSON for documentation
        summary = {
            "experiment_id": str(exp.id),
            "total_funds": len(SAMPLE_FUNDS),
            "success_count": success_count,
            "failure_count": failure_count,
            "failure_taxonomy": dict(failure_taxonomy),
            "te_distribution": {
                "min": tes[0] if tes else None,
                "median": tes[len(tes) // 2] if tes else None,
                "max": tes[-1] if tes else None,
                "mean": sum(tes) / len(tes) if tes else None,
            },
            "confidence_levels": dict(confidence_counts),
        }
        print("\n=== Summary JSON ===")
        print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
