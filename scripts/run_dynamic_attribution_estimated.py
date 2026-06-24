"""Run dynamic attribution with estimated holdings (from simulated holding).

Verifies the P1 integration: dynamic_attribution can consume
SimulatedHoldingResult rows as input, with clear disclosed vs estimated
separation in the output metrics and warnings.

Prerequisite: run_simulated_holding_30funds.py must have been run first
so that SimulatedHoldingResult rows exist for the sample funds.

Usage:
    .venv\\Scripts\\python.exe scripts\\run_dynamic_attribution_estimated.py
"""

from __future__ import annotations

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


def main() -> None:
    engine = get_engine()
    with Session(engine) as db:
        exp = create_experiment(
            db,
            experiment_name="P2 dynamic_attribution estimated-holdings 30-fund",
            algorithm_name="dynamic_attribution",
            algorithm_version="0.1.0",
            parameters={
                "holdings_source": "estimated",
                "min_return_observations": 20,
            },
            sample_fund_codes=SAMPLE_FUNDS,
        )
        print(f"Created experiment id={exp.id}")

        results = dispatch_run(db, exp)
        db.commit()

        success_count = sum(1 for r in results if r.get("is_success"))
        failure_count = len(results) - success_count
        print(f"\nRun complete: {success_count}/{len(results)} succeeded, {failure_count} failed")

        exp_results = db.scalars(
            select(ExperimentResult).where(ExperimentResult.experiment_id == exp.id)
        ).all()

        print("\n=== Per-fund results ===")
        print(f"{'fund':8s} {'success':>8s} {'periods':>8s} {'residual':>10s} {'holdings_src':>14s} {'warnings':>8s}")
        for r in exp_results:
            metrics = r.metrics or {}
            periods = metrics.get("period_count", 0)
            residual = metrics.get("estimated_total_residual")
            src = metrics.get("holdings_source", "?")
            uses_est = metrics.get("uses_estimated_holdings")
            warning_count = len(r.warnings or [])
            res_str = f"{residual:.4f}" if residual is not None else "N/A"
            print(
                f"{r.fund_code:8s} {str(r.is_success):>8s} {periods:>8d} "
                f"{res_str:>10s} {src:>14s} {warning_count:>8d}"
            )

        # Verify separation: all results should have holdings_source=estimated
        # and uses_estimated_holdings=True
        print("\n=== Separation check ===")
        all_estimated = all(
            (r.metrics or {}).get("holdings_source") == "estimated"
            for r in exp_results
            if r.is_success
        )
        all_flagged = all(
            (r.metrics or {}).get("uses_estimated_holdings") is True
            for r in exp_results
            if r.is_success
        )
        has_warning = any(
            "estimated" in " ".join(r.warnings or []).lower()
            for r in exp_results
            if r.is_success
        )
        print(f"  all holdings_source=estimated: {all_estimated}")
        print(f"  all uses_estimated_holdings=True: {all_flagged}")
        print(f"  has estimated warning: {has_warning}")

        # Show a sample warning
        for r in exp_results:
            if r.is_success and r.warnings:
                print(f"\n  Sample warnings for {r.fund_code}:")
                for w in r.warnings[:3]:
                    print(f"    - {w}")
                break

        # Summary
        residuals = [
            (r.metrics or {}).get("estimated_total_residual")
            for r in exp_results
            if r.is_success and (r.metrics or {}).get("estimated_total_residual") is not None
        ]
        if residuals:
            residuals.sort()
            print("\n=== Residual distribution ===")
            print(f"  min:    {min(residuals):.4f}")
            print(f"  median: {residuals[len(residuals)//2]:.4f}")
            print(f"  max:    {max(residuals):.4f}")


if __name__ == "__main__":
    main()
