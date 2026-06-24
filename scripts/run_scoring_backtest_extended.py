"""Run extended scoring backtest spanning 2021-2025 (bull/bear cycle).

The previous backtest only covered 2024-03-31 to 2025-03-31, which fell
entirely within the 2024-2025 A-share bull market. This caused structural
IC reversal. This script extends the window to 2021-03-31 to 2025-03-31
to span a full bull/bear cycle, giving the scoring formula a fairer test.

NAV data already covers 2001-2026 (107k rows for 30 funds). Holdings data
only covers 2023-2026, so the style_stability and trading dimensions will
be limited for 2021-2022 eval dates — dynamic weight redistribution will
handle this.

Usage:
    .venv\\Scripts\\python.exe scripts\\run_scoring_backtest_extended.py
"""

from __future__ import annotations

import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_research.analysis.scoring import ALGORITHM_VERSION
from fund_research.db.models import ExperimentResult, ScoringBacktest
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
            experiment_name=f"P2 scoring v{ALGORITHM_VERSION} 30-fund extended 2021-2025",
            algorithm_name="scoring",
            algorithm_version=ALGORITHM_VERSION,
            parameters={
                "preset": "均衡型",
                "forward_months": 12,
                "min_forward_observations": 60,
                "score_version": ALGORITHM_VERSION,
            },
            sample_fund_codes=SAMPLE_FUNDS,
            backtest_start=date(2021, 3, 31),
            backtest_end=date(2025, 3, 31),
        )
        print(f"Created experiment id={exp.id}")

        results = dispatch_run(db, exp)
        db.commit()

        success = sum(1 for r in results if r.get("is_success"))
        print(f"Run complete: {success}/{len(results)} funds succeeded")

        # Pull the persisted scoring backtest row for this run.
        sb = db.scalar(
            select(ScoringBacktest)
            .where(ScoringBacktest.score_version == ALGORITHM_VERSION)
            .order_by(ScoringBacktest.backtest_date.desc())
            .limit(1)
        )
        if sb is None:
            print("No ScoringBacktest row found")
            return

        print(f"\n=== Scoring Backtest v{ALGORITHM_VERSION} Extended (2021-2025) ===")
        print(f"IC mean: {sb.ic_mean}")
        print(f"IC IR:   {sb.ic_ir}")
        print(f"Monotonicity check: {sb.monotonicity_check}")
        print(f"Group count: {sb.group_count}")
        print(f"Group results: {json.dumps(sb.group_results, indent=2, ensure_ascii=False)}")
        print(f"Detail: {json.dumps(sb.detail, indent=2, ensure_ascii=False)}")

        # Per-fund eval counts
        exp_results = db.scalars(
            select(ExperimentResult).where(ExperimentResult.experiment_id == exp.id)
        ).all()
        print(f"\nPer-fund results: {len(exp_results)}")
        for r in exp_results[:5]:
            print(
                f"  {r.fund_code}: success={r.is_success} "
                f"metrics_keys={list((r.metrics or {}).keys())[:5]}"
            )


if __name__ == "__main__":
    main()
