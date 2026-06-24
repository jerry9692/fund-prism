"""Backfill StyleExposureResult from AKShare industry allocation data.

Uses fund_portfolio_industry_allocation_em to fetch disclosed industry
weights for each fund-year, then persists them as StyleExposureResult
rows with exposure_type='industry'. This feeds compute_style_stability.

Usage:
    .venv\\Scripts\\python.exe scripts\\backfill_industry_exposure.py
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fund_research.data.adapters.akshare import AkshareAdapter
from fund_research.data.update import (
    _apply_industry_allocation_result,
    _snapshot_from_fetch,
)
from fund_research.db.models import StyleExposureResult
from fund_research.db.session import get_engine

SAMPLE_FUNDS_PATH = Path("data/samples/sample_funds_v0.1.csv")
YEARS = [2023, 2024, 2025]


def load_sample_funds() -> list[str]:
    with SAMPLE_FUNDS_PATH.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [row["fund_code"] for row in reader]


def main() -> None:
    fund_codes = load_sample_funds()
    print(f"Backfilling industry exposure for {len(fund_codes)} funds, years={YEARS}")

    adapter = AkshareAdapter()
    engine = get_engine()

    total_inserted = 0
    total_updated = 0
    total_skipped = 0
    failures: list[str] = []

    with Session(engine) as db:
        for fund_code in fund_codes:
            for year in YEARS:
                try:
                    result = adapter.fetch_fund_industry_allocation(
                        fund_code, report_date=date(year, 12, 31)
                    )
                    _snapshot_from_fetch(db, result)
                    if not result.is_success or result.data is None or result.data.empty:
                        total_skipped += 1
                        failures.append(f"{fund_code}/{year}: {result.error_message or 'empty'}")
                        continue

                    rows = result.data.to_dict(orient="records")
                    action = _apply_industry_allocation_result(
                        db, rows, fund_code, date(year, 12, 31), dry_run=False
                    )
                    if action == "inserted":
                        total_inserted += 1
                    elif action == "updated":
                        total_updated += 1
                    else:
                        total_skipped += 1
                    print(f"  {fund_code} {year}: {action} ({len(rows)} rows)")

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
        total = db.scalar(select(func.count()).select_from(StyleExposureResult)) or 0
        funds = db.scalar(
            select(func.count(func.distinct(StyleExposureResult.fund_code)))
        ) or 0
        dates = db.scalars(
            select(func.distinct(StyleExposureResult.calc_date))
            .order_by(StyleExposureResult.calc_date)
        ).all()
        types = db.scalars(
            select(func.distinct(StyleExposureResult.exposure_type))
        ).all()
        print("\n=== Final state ===")
        print(f"total rows: {total}")
        print(f"distinct funds: {funds}")
        print(f"distinct calc_dates: {len(dates)}")
        print(f"exposure_types: {types}")
        print(f"date range: {dates[0] if dates else 'N/A'} -> {dates[-1] if dates else 'N/A'}")


if __name__ == "__main__":
    main()
