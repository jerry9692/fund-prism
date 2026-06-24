"""Diagnose scoring dimension data coverage across the backtest window."""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fund_research.db.models import (
    FundDisclosedHoldings,
    FundManagerTenure,
    FundScale,
    HolderStructure,
    StaticAttributionResult,
    StyleExposureResult,
)
from fund_research.db.session import get_engine

SAMPLE_FUNDS = [
    "000001", "020005", "070002", "110009", "163406", "260108", "519068",
    "002939", "005827", "161005", "166002", "450002", "519736", "000697",
    "001071", "001938", "003095", "004851", "005267", "006228", "110022",
    "340007", "519712", "540003", "570001", "000409", "001480", "519772",
    "000978", "001810",
]

EVAL_DATES = [
    date(2024, 3, 31), date(2024, 6, 30), date(2024, 9, 30),
    date(2024, 12, 31), date(2025, 3, 31),
]


def main() -> None:
    engine = get_engine()
    with Session(engine) as db:
        print("=== Scoring dimension data coverage by eval date ===\n")
        for eval_date in EVAL_DATES:
            print(f"--- eval_date={eval_date} ---")
            for label, model, date_col in [
                ("StaticAttributionResult", StaticAttributionResult, StaticAttributionResult.report_date),
                ("StyleExposureResult", StyleExposureResult, StyleExposureResult.calc_date),
                ("FundScale", FundScale, FundScale.report_date),
                ("HolderStructure", HolderStructure, HolderStructure.report_date),
                ("FundManagerTenure", FundManagerTenure, FundManagerTenure.start_date),
                ("FundDisclosedHoldings(股票)", FundDisclosedHoldings, FundDisclosedHoldings.report_date),
            ]:
                count = db.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.fund_code.in_(SAMPLE_FUNDS))
                    .where(date_col <= eval_date)
                )
                print(f"  {label:30s}: {count} rows <= {eval_date}")
            print()


if __name__ == "__main__":
    main()
