"""Backfill historical fund manager tenure and holder structure data.

Uses Eastmoney F10 web scraping (C-level data source) to populate:
- FundManagerTenure: complete historical manager changes (with start_date/end_date)
- HolderStructure: semi-annual institutional/individual/employee holding ratios
"""
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from fund_research.config.settings import get_settings
from fund_research.data.adapters.akshare import AkshareAdapter
from fund_research.data.update import (
    UpdateSummary,
    upsert_akshare_holder_structure,
    upsert_eastmoney_fund_manager_history,
)
from fund_research.db.models import FundMain, FundManagerTenure, HolderStructure
from fund_research.db.session import create_engine_from_path, init_db


def main() -> None:
    settings = get_settings()
    sample_path = settings.sample_funds_path_absolute
    db_path = settings.db_path_absolute
    print(f"Database: {db_path}")
    print(f"Sample funds: {sample_path}")

    init_db(db_path)
    engine = create_engine_from_path(db_path)
    session_factory = sessionmaker(bind=engine)

    adapter = AkshareAdapter()

    import csv

    fund_codes: set[str] = set()
    with open(sample_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            code = row.get("fund_code", "").strip()
            if code:
                fund_codes.add(code)
    print(f"Found {len(fund_codes)} sample funds")

    with session_factory() as session:
        before_mgr_count = session.query(FundManagerTenure).count()
        before_holder_count = session.query(HolderStructure).count()
        print(f"Before: {before_mgr_count} tenure rows, {before_holder_count} holder rows")

    print("\n=== Step 1: Backfill fund manager history (Eastmoney F10) ===")
    with session_factory() as session:
        summary = upsert_eastmoney_fund_manager_history(
            session, fund_codes, adapter=adapter, request_interval=1.2, dry_run=False
        )
        _print_summary(summary)
        after_mgr_count = session.query(FundManagerTenure).count()
        print(f"  Manager tenure rows after: {after_mgr_count}")

    print("\n=== Step 2: Backfill holder structure (Eastmoney F10) ===")
    with session_factory() as session:
        summary = upsert_akshare_holder_structure(
            session, fund_codes, adapter=adapter, request_interval=1.0, dry_run=False
        )
        _print_summary(summary)
        after_holder_count = session.query(HolderStructure).count()
        print(f"  Holder structure rows after: {after_holder_count}")

    print("\n=== Coverage check ===")
    with session_factory() as session:
        funds_with_tenure = session.query(FundManagerTenure.fund_code).distinct().count()
        funds_with_holder = session.query(HolderStructure.fund_code).distinct().count()
        print(f"  Funds with manager tenure data: {funds_with_tenure}/{len(fund_codes)}")
        print(f"  Funds with holder structure data: {funds_with_holder}/{len(fund_codes)}")

        backtest_dates = [date(y, 12, 31) for y in range(2021, 2026)]
        for as_of in backtest_dates:
            active_mgrs = (
                session.query(FundManagerTenure.fund_code)
                .filter(FundManagerTenure.start_date <= as_of)
                .filter(
                    (FundManagerTenure.end_date.is_(None))
                    | (FundManagerTenure.end_date > as_of)
                )
                .distinct()
                .count()
            )
            holders = (
                session.query(HolderStructure.fund_code)
                .filter(HolderStructure.report_date <= as_of)
                .distinct()
                .count()
            )
            print(
                f"  As of {as_of}: {active_mgrs}/{len(fund_codes)} funds have active managers, "
                f"{holders}/{len(fund_codes)} have holder structure"
            )


def _print_summary(s: UpdateSummary) -> None:
    print(
        f"  {s.entity}: inserted={s.inserted}, updated={s.updated}, "
        f"skipped={s.skipped}, requested={s.requested}"
    )
    if s.warnings:
        for w in s.warnings[:5]:
            print(f"    warning: {w}")
        if len(s.warnings) > 5:
            print(f"    ... and {len(s.warnings) - 5} more warnings")


if __name__ == "__main__":
    main()
