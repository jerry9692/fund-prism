"""Run the 30-fund scoring backtest to validate the v0.3 scoring fixes.

This script creates a scoring backtest experiment over the same
2024-03-31 to 2025-03-31 window used by the previous failed run, then
prints the IC / monotonicity / group-return summary so we can confirm
the lookahead-bias fix and weight rebalance improved predictive power.

Usage:
    .venv\\Scripts\\python.exe scripts\\run_scoring_backtest_validation.py
"""

from __future__ import annotations

import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.analysis.scoring import ALGORITHM_VERSION
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
            experiment_name=f"P2 scoring v{ALGORITHM_VERSION} 30-fund 12m backtest 2024-2025",
            algorithm_name="scoring",
            algorithm_version=ALGORITHM_VERSION,
            parameters={
                "preset": "均衡型",
                "forward_months": 12,
                "min_forward_observations": 60,
                "score_version": ALGORITHM_VERSION,
            },
            sample_fund_codes=SAMPLE_FUNDS,
            backtest_start=date(2024, 3, 31),
            backtest_end=date(2025, 3, 31),
        )
        print(f"Created experiment id={exp.id}")

        results = dispatch_run(db, exp)
        db.commit()

        success = sum(1 for r in results if r.get("is_success"))
        print(f"Run complete: {success}/{len(results)} funds succeeded")

        # Pull the persisted scoring backtest row for this run.
        from fund_research.db.models import ScoringBacktest

        sb = db.scalar(
            select(ScoringBacktest)
            .where(ScoringBacktest.score_version == ALGORITHM_VERSION)
            .order_by(ScoringBacktest.backtest_date.desc())
            .limit(1)
        )
        if sb is None:
            print("No ScoringBacktest row found")
            return

        print(f"\n=== Scoring Backtest v{ALGORITHM_VERSION} Summary ===")
        print(f"IC mean: {sb.ic_mean}")
        print(f"IC IR:   {sb.ic_ir}")
        print(f"Monotonicity check: {sb.monotonicity_check}")
        print(f"Group count: {sb.group_count}")
        print(f"Group results: {json.dumps(sb.group_results, indent=2, ensure_ascii=False)}")
        print(f"Detail: {json.dumps(sb.detail, indent=2, ensure_ascii=False)}")

        # Also print per-fund eval counts.
        exp_results = db.scalars(
            select(ExperimentResult).where(ExperimentResult.experiment_id == exp.id)
        ).all()
        print(f"\nPer-fund results: {len(exp_results)}")
        for r in exp_results[:5]:
            print(f"  {r.fund_code}: success={r.is_success} metrics_keys={list((r.metrics or {}).keys())[:5]}")


if __name__ == "__main__":
    main()
