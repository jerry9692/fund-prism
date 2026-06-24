"""Backfill 2021-2023 NAV and holdings data to extend the scoring backtest window.

The current scoring backtest only covers 2024-03-31 to 2025-03-31, which falls
entirely within the 2024-2025 A-share bull market. This causes structural IC
reversal — historically "good" funds (low risk, high Sharpe) underperform in
the subsequent bull run. Extending the window to 2021-2025 spans a full
bull/bear cycle, giving the scoring formula a fairer test.

This script backfills:
- Fund NAV (daily) for 2021-01-01 to 2023-12-31
- Fund disclosed holdings for years 2021, 2022 (2023 already backfilled)

Usage:
    .venv\\Scripts\\python.exe scripts\\backfill_2021_2023_data.py
"""

from __future__ import annotations

import csv
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fund_research.data.adapters.akshare import AkshareAdapter
from fund_research.data.update import _apply_holding_row, _snapshot_from_fetch
from fund_research.db.models import FundDisclosedHoldings, FundNAV
from fund_research.db.session import get_engine

SAMPLE_FUNDS_PATH = Path("data/samples/sample_funds_v0.1.csv")
NAV_START = date(2021, 1, 1)
NAV_END = date(2023, 12, 31)
HOLDINGS_YEARS = [2021, 2022]


def load_sample_funds() -> list[str]:
    with SAMPLE_FUNDS_PATH.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [row["fund_code"] for row in reader]


def backfill_nav(fund_codes: list[str]) -> None:
    """Backfill daily NAV for 2021-2023."""
    adapter = AkshareAdapter()
    engine = get_engine()

    total_inserted = 0
    total_skipped = 0
    failures: list[str] = []

    with Session(engine) as db:
        for i, fund_code in enumerate(fund_codes, 1):
            try:
                result = adapter.fetch_fund_nav(
                    fund_code, start_date=NAV_START, end_date=NAV_END
                )
                _snapshot_from_fetch(db, result)
                if not result.is_success or result.data is None or result.data.empty:
                    total_skipped += 1
                    failures.append(
                        f"{fund_code}: {result.error_message or 'empty'}"
                    )
                    continue

                rows = result.data.to_dict(orient="records")
                fund_inserted = 0
                for row in rows:
                    trade_date_raw = row.get("trade_date")
                    if trade_date_raw is None:
                        continue
                    trade_date_str = str(trade_date_raw)[:10]
                    try:
                        trade_date = date.fromisoformat(trade_date_str)
                    except ValueError:
                        continue

                    existing = db.scalar(
                        select(FundNAV).where(
                            FundNAV.fund_code == fund_code,
                            FundNAV.trade_date == trade_date,
                        )
                    )
                    if existing is not None:
                        continue

                    unit_nav = row.get("unit_nav")
                    accumulated_nav = row.get("accumulated_nav")
                    daily_return = row.get("daily_return")
                    nav_row = FundNAV(
                        fund_code=fund_code,
                        trade_date=trade_date,
                        unit_nav=float(unit_nav) if unit_nav else None,
                        accumulated_nav=float(accumulated_nav)
                        if accumulated_nav
                        else None,
                        daily_return=float(daily_return)
                        if daily_return is not None
                        else None,
                    )
                    db.add(nav_row)
                    fund_inserted += 1

                total_inserted += fund_inserted
                if i % 5 == 0 or fund_inserted == 0:
                    print(
                        f"  NAV [{i}/{len(fund_codes)}] {fund_code}: +{fund_inserted} rows",
                        file=sys.stderr,
                    )

            except Exception as exc:
                total_skipped += 1
                failures.append(f"{fund_code}: {exc}")
                print(f"  NAV {fund_code}: ERROR {exc}", file=sys.stderr)

        db.commit()

    print("\n=== NAV Summary ===")
    print(f"inserted: {total_inserted}")
    print(f"skipped/failed: {total_skipped}")
    if failures:
        print(f"failures ({len(failures)}):")
        for f in failures[:5]:
            print(f"  {f}")


def backfill_holdings(fund_codes: list[str]) -> None:
    """Backfill disclosed holdings for 2021-2022."""
    adapter = AkshareAdapter()
    engine = get_engine()

    total_inserted = 0
    total_updated = 0
    total_skipped = 0
    failures: list[str] = []

    with Session(engine) as db:
        for fund_code in fund_codes:
            for year in HOLDINGS_YEARS:
                try:
                    result = adapter.fetch_fund_holdings(
                        fund_code, report_date=date(year, 12, 31)
                    )
                    _snapshot_from_fetch(db, result)
                    if (
                        not result.is_success
                        or result.data is None
                        or result.data.empty
                    ):
                        total_skipped += 1
                        failures.append(
                            f"{fund_code}/{year}: {result.error_message or 'empty'}"
                        )
                        continue

                    rows = result.data.to_dict(orient="records")
                    fund_inserted = 0
                    fund_updated = 0
                    for row in rows:
                        action = _apply_holding_row(
                            db, row, fund_code, None, dry_run=False
                        )
                        if action == "inserted":
                            fund_inserted += 1
                        elif action == "updated":
                            fund_updated += 1

                    total_inserted += fund_inserted
                    total_updated += fund_updated
                    total_skipped += len(rows) - fund_inserted - fund_updated
                    print(
                        f"  Holdings {fund_code} {year}: +{fund_inserted} ~{fund_updated}",
                        file=sys.stderr,
                    )

                except Exception as exc:
                    total_skipped += 1
                    failures.append(f"{fund_code}/{year}: {exc}")
                    print(
                        f"  Holdings {fund_code} {year}: ERROR {exc}",
                        file=sys.stderr,
                    )

        db.commit()

    print("\n=== Holdings Summary ===")
    print(f"inserted: {total_inserted}")
    print(f"updated:  {total_updated}")
    print(f"skipped:  {total_skipped}")
    if failures:
        print(f"failures ({len(failures)}):")
        for f in failures[:5]:
            print(f"  {f}")


def verify_final_state() -> None:
    """Print final data coverage."""
    engine = get_engine()
    with Session(engine) as db:
        nav_count = db.scalar(select(func.count()).select_from(FundNAV)) or 0
        nav_min = db.scalar(select(func.min(FundNAV.trade_date)))
        nav_max = db.scalar(select(func.max(FundNAV.trade_date)))
        nav_funds = db.scalar(
            select(func.count(func.distinct(FundNAV.fund_code)))
        ) or 0

        holdings_count = (
            db.scalar(select(func.count()).select_from(FundDisclosedHoldings)) or 0
        )
        holdings_dates = db.scalars(
            select(func.distinct(FundDisclosedHoldings.report_date))
            .order_by(FundDisclosedHoldings.report_date)
        ).all()
        holdings_funds = db.scalar(
            select(func.count(func.distinct(FundDisclosedHoldings.fund_code)))
        ) or 0

    print("\n=== Final State ===")
    print(f"NAV: {nav_count} rows, {nav_funds} funds, range {nav_min} to {nav_max}")
    print(
        f"Holdings: {holdings_count} rows, {holdings_funds} funds, "
        f"{len(holdings_dates)} report dates"
    )
    print(f"Holdings report dates: {holdings_dates}")


def main() -> None:
    fund_codes = load_sample_funds()
    print(
        f"Backfilling 2021-2023 data for {len(fund_codes)} funds",
        file=sys.stderr,
    )

    backfill_nav(fund_codes)
    backfill_holdings(fund_codes)
    verify_final_state()


if __name__ == "__main__":
    main()
