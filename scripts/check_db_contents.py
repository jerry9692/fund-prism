"""Check row counts across all scoring-relevant tables."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fund_research.db.models import (
    FundDisclosedHoldings,
    FundMain,
    FundManagerTenure,
    FundNAV,
    FundScale,
    HolderStructure,
    StaticAttributionResult,
    StyleExposureResult,
)
from fund_research.db.session import get_engine

SAMPLE_3 = ["000001", "020005", "070002"]

TABLES = [
    ("FundNAV", FundNAV),
    ("FundMain", FundMain),
    ("FundDisclosedHoldings", FundDisclosedHoldings),
    ("FundScale", FundScale),
    ("HolderStructure", HolderStructure),
    ("FundManagerTenure", FundManagerTenure),
    ("StaticAttributionResult", StaticAttributionResult),
    ("StyleExposureResult", StyleExposureResult),
]


def main() -> None:
    engine = get_engine()
    with Session(engine) as db:
        print("=== Table row counts ===")
        for name, model in TABLES:
            total = db.scalar(select(func.count()).select_from(model)) or 0
            sample = db.scalar(
                select(func.count())
                .select_from(model)
                .where(model.fund_code.in_(SAMPLE_3))
            ) or 0
            print(f"  {name:30s}: total={total:8d}  sample3={sample}")

        # NAV date range for sample funds
        print("\n=== FundNAV date range for sample 3 ===")
        for code in SAMPLE_3:
            row = db.execute(
                select(
                    func.min(FundNAV.trade_date),
                    func.max(FundNAV.trade_date),
                    func.count(),
                ).where(FundNAV.fund_code == code)
            ).one()
            print(f"  {code}: {row[0]} -> {row[1]}  ({row[2]} rows)")

        # Distinct fund codes in NAV
        nav_codes = db.scalar(select(func.count(func.distinct(FundNAV.fund_code)))) or 0
        print(f"\nDistinct fund codes in FundNAV: {nav_codes}")


if __name__ == "__main__":
    main()
