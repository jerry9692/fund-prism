"""Check StockDaily coverage for simulated holding feasibility."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fund_research.db.models import FundDisclosedHoldings, FundNAV, StockDaily
from fund_research.db.session import get_engine

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
        # StockDaily totals
        total = db.scalar(select(func.count()).select_from(StockDaily)) or 0
        distinct_stocks = db.scalar(
            select(func.count(func.distinct(StockDaily.stock_code)))
        ) or 0
        print(f"StockDaily: {total} rows, {distinct_stocks} distinct stocks")

        if distinct_stocks > 0:
            dmin, dmax = db.execute(
                select(func.min(StockDaily.trade_date), func.max(StockDaily.trade_date))
            ).one()
            print(f"  date range: {dmin} -> {dmax}")

        # Per-fund holdings + stock match coverage
        print("\n=== Per-fund holdings/stock coverage (30 funds) ===")
        print(f"{'fund':8s} {'holdings':>9s} {'stocks_matched':>15s} {'nav_rows':>9s}")
        for code in SAMPLE_FUNDS:
            h_count = db.scalar(
                select(func.count())
                .select_from(FundDisclosedHoldings)
                .where(FundDisclosedHoldings.fund_code == code)
                .where(FundDisclosedHoldings.asset_type == "股票")
            ) or 0
            nav_count = db.scalar(
                select(func.count())
                .select_from(FundNAV)
                .where(FundNAV.fund_code == code)
            ) or 0
            # Get distinct stock codes from holdings
            holding_codes = db.scalars(
                select(func.distinct(FundDisclosedHoldings.security_code))
                .where(FundDisclosedHoldings.fund_code == code)
                .where(FundDisclosedHoldings.asset_type == "股票")
            ).all()
            matched = 0
            if holding_codes:
                matched = db.scalar(
                    select(func.count(func.distinct(StockDaily.stock_code)))
                    .where(StockDaily.stock_code.in_(holding_codes))
                ) or 0
            print(f"{code:8s} {h_count:9d} {matched:15d} {nav_count:9d}")


if __name__ == "__main__":
    main()
