"""Backfill historical FundDisclosedHoldings for 30 sample funds.

Uses AKShare fund_portfolio_hold_em to fetch holdings for years 2023-2025
(12 report periods total). This is the only historical data source we
can backfill — FundScale, HolderStructure, and FundManagerTenure have no
historical endpoints in AKShare.

Usage:
    .venv\\Scripts\\python.exe scripts\\backfill_historical_holdings.py
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fund_research.data.adapters.akshare import AkshareAdapter
from fund_research.data.update import _apply_holding_row, _snapshot_from_fetch
from fund_research.db.models import FundDisclosedHoldings
from fund_research.db.session import get_engine

SAMPLE_FUNDS_PATH = Path("data/samples/sample_funds_v0.1.csv")
YEARS = [2023, 2024, 2025]


def load_sample_funds() -> list[str]:
    with SAMPLE_FUNDS_PATH.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [row["fund_code"] for row in reader]


def main() -> None:
    fund_codes = load_sample_funds()
    print(f"Backfilling holdings for {len(fund_codes)} funds, years={YEARS}")

    adapter = AkshareAdapter()
    engine = get_engine()

    total_inserted = 0
    total_updated = 0
    total_skipped = 0
    failures: list[str] = []

    with Session(engine) as db:
        # Check existing data
        existing_count = db.scalar(
            select(func.count(func.distinct(FundDisclosedHoldings.report_date)))
        ) or 0
        existing_dates = db.scalars(
            select(func.distinct(FundDisclosedHoldings.report_date))
            .order_by(FundDisclosedHoldings.report_date.desc())
            .limit(10)
        ).all()
        print(f"Existing distinct report_dates: {existing_count}")
        print(f"Recent dates: {existing_dates}")

        for fund_code in fund_codes:
            for year in YEARS:
                try:
                    result = adapter.fetch_fund_holdings(
                        fund_code, report_date=date(year, 12, 31)
                    )
                    _snapshot_from_fetch(db, result)
                    if not result.is_success or result.data is None or result.data.empty:
                        total_skipped += 1
                        failures.append(f"{fund_code}/{year}: {result.error_message or 'empty'}")
                        continue

                    rows = result.data.to_dict(orient="records")
                    fund_inserted = 0
                    fund_updated = 0
                    for row in rows:
                        action = _apply_holding_row(db, row, fund_code, None, dry_run=False)
                        if action == "inserted":
                            fund_inserted += 1
                        elif action == "updated":
                            fund_updated += 1

                    total_inserted += fund_inserted
                    total_updated += fund_updated
                    total_skipped += len(rows) - fund_inserted - fund_updated
                    print(
                        f"  {fund_code} {year}: +{fund_inserted} ~{fund_updated} "
                        f"(total rows: {len(rows)})"
                    )

                except Exception as exc:
                    total_skipped += 1
                    failures.append(f"{fund_code}/{year}: {exc}")
                    print(f"  {fund_code} {year}: ERROR {exc}")

        db.commit()

    print("\n=== Summary ===")
    print(f"inserted: {total_inserted}")
    print(f"updated:  {total_updated}")
    print(f"skipped:  {total_skipped}")
    print(f"failures: {len(failures)}")
    if failures:
        print("\nFirst 10 failures:")
        for f in failures[:10]:
            print(f"  {f}")

    # Verify final state
    with Session(engine) as db:
        final_count = db.scalar(select(func.count()).select_from(FundDisclosedHoldings)) or 0
        final_dates = db.scalars(
            select(func.distinct(FundDisclosedHoldings.report_date))
            .order_by(FundDisclosedHoldings.report_date)
        ).all()
        final_funds = db.scalar(
            select(func.count(func.distinct(FundDisclosedHoldings.fund_code)))
        ) or 0
        print("\n=== Final state ===")
        print(f"total rows: {final_count}")
        print(f"distinct funds: {final_funds}")
        print(f"distinct report_dates: {len(final_dates)}")
        print(f"all report_dates: {final_dates}")


if __name__ == "__main__":
    main()
