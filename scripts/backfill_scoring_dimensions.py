"""Backfill the 4 missing scoring dimensions for 30 sample funds.

The per-dimension IC diagnostics showed alpha/scale/team/holder have 0%
coverage in the 30-fund sample. This script backfills:

- FundScale via upsert_akshare_fund_scale (latest snapshot)
- HolderStructure via upsert_akshare_holder_structure
- FundManagerTenure via upsert_akshare_fund_managers
- StaticAttributionResult via the /api/v1/funds/{code}/exposure endpoint
  (computes static attribution from disclosed holdings + stock returns)

Usage:
    .venv\\Scripts\\python.exe scripts\\backfill_scoring_dimensions.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fund_research.data.update import (
    upsert_akshare_fund_managers,
    upsert_akshare_fund_scale,
    upsert_akshare_holder_structure,
)
from fund_research.db.models import (
    FundDisclosedHoldings,
    FundManagerTenure,
    FundScale,
    HolderStructure,
    StaticAttributionResult,
)
from fund_research.db.session import get_engine

SAMPLE_FUNDS_PATH = Path("data/samples/sample_funds_v0.1.csv")


def load_sample_funds() -> list[str]:
    with SAMPLE_FUNDS_PATH.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [row["fund_code"] for row in reader]


def _count_table(session: Session, model, fund_code: str | None = None) -> int:
    stmt = select(func.count()).select_from(model)
    if fund_code is not None:
        stmt = stmt.where(model.fund_code == fund_code)
    return int(session.scalar(stmt) or 0)


def backfill_scale_and_holder_and_managers(fund_codes: list[str]) -> dict:
    """Backfill FundScale, HolderStructure, FundManagerTenure via AKShare."""
    print(f"\n=== Backfilling scale/holder/managers for {len(fund_codes)} funds ===")
    engine = get_engine()
    results: dict[str, dict] = {}

    with Session(engine) as db:
        # Pre-counts
        pre_scale = _count_table(db, FundScale)
        pre_holder = _count_table(db, HolderStructure)
        pre_manager = _count_table(db, FundManagerTenure)
        print(f"Pre: scale={pre_scale}, holder={pre_holder}, manager={pre_manager}")

        fund_set = set(fund_codes)

        print("\n--- FundScale ---")
        scale_summary = upsert_akshare_fund_scale(db, fund_set)
        print(
            f"  inserted={scale_summary.inserted} "
            f"updated={scale_summary.updated} "
            f"skipped={scale_summary.skipped}"
        )

        print("\n--- HolderStructure ---")
        holder_summary = upsert_akshare_holder_structure(db, fund_set)
        print(
            f"  inserted={holder_summary.inserted} "
            f"updated={holder_summary.updated} "
            f"skipped={holder_summary.skipped}"
        )

        print("\n--- FundManagerTenure ---")
        manager_summary = upsert_akshare_fund_managers(db, fund_set)
        print(
            f"  inserted={manager_summary.inserted} "
            f"updated={manager_summary.updated} "
            f"skipped={manager_summary.skipped}"
        )

        # Post-counts
        post_scale = _count_table(db, FundScale)
        post_holder = _count_table(db, HolderStructure)
        post_manager = _count_table(db, FundManagerTenure)
        print(f"\nPost: scale={post_scale}, holder={post_holder}, manager={post_manager}")

        results["scale"] = {
            "pre": pre_scale, "post": post_scale,
            "inserted": scale_summary.inserted, "updated": scale_summary.updated,
        }
        results["holder"] = {
            "pre": pre_holder, "post": post_holder,
            "inserted": holder_summary.inserted, "updated": holder_summary.updated,
        }
        results["manager"] = {
            "pre": pre_manager, "post": post_manager,
            "inserted": manager_summary.inserted, "updated": manager_summary.updated,
        }

    return results


def backfill_static_attribution(fund_codes: list[str]) -> dict:
    """Backfill StaticAttributionResult by computing from disclosed holdings.

    Uses the same logic as the /api/v1/funds/{code}/exposure endpoint but
    runs it directly via the attribution module for each fund's latest
    disclosed holding period.
    """
    print(f"\n=== Backfilling StaticAttributionResult for {len(fund_codes)} funds ===")
    engine = get_engine()
    inserted = 0
    skipped = 0
    failed: list[str] = []

    with Session(engine) as db:
        pre_count = _count_table(db, StaticAttributionResult)
        print(f"Pre: static_attribution={pre_count}")

        for fund_code in fund_codes:
            try:
                # Find latest disclosed holding report_date with stock holdings
                latest_report_date = db.scalar(
                    select(FundDisclosedHoldings.report_date)
                    .where(FundDisclosedHoldings.fund_code == fund_code)
                    .where(FundDisclosedHoldings.asset_type == "股票")
                    .order_by(FundDisclosedHoldings.report_date.desc())
                    .limit(1)
                )
                if latest_report_date is None:
                    skipped += 1
                    failed.append(f"{fund_code}: no stock holdings")
                    continue

                # Check if attribution already exists for this fund+date
                existing = db.scalar(
                    select(StaticAttributionResult)
                    .where(StaticAttributionResult.fund_code == fund_code)
                    .where(StaticAttributionResult.report_date == latest_report_date)
                )
                if existing is not None:
                    skipped += 1
                    continue

                # Use the API endpoint logic to compute and persist.
                # The function picks the latest disclosed holding report_date
                # internally, so we pass end_date=None to use the latest.
                from fund_research.api.router import _run_static_attribution_for_latest_holdings
                _run_static_attribution_for_latest_holdings(db, fund_code, end_date=None)
                db.commit()
                inserted += 1
                print(f"  {fund_code}: attribution computed for {latest_report_date}")

            except Exception as exc:
                db.rollback()
                skipped += 1
                failed.append(f"{fund_code}: {exc}")
                print(f"  {fund_code}: ERROR {exc}")

        post_count = _count_table(db, StaticAttributionResult)
        print(f"\nPost: static_attribution={post_count}")

    return {
        "pre": pre_count,
        "post": post_count,
        "inserted": inserted,
        "skipped": skipped,
        "failures": failed[:10],
    }


def verify_dimension_coverage(fund_codes: list[str]) -> dict:
    """Verify per-dimension data coverage after backfill."""
    print("\n=== Dimension coverage verification ===")
    engine = get_engine()
    coverage: dict[str, int] = {}

    with Session(engine) as db:
        for fund_code in fund_codes:
            coverage.setdefault("scale", 0)
            coverage.setdefault("holder", 0)
            coverage.setdefault("team", 0)
            coverage.setdefault("alpha", 0)

            if _count_table(db, FundScale, fund_code) > 0:
                coverage["scale"] += 1
            if _count_table(db, HolderStructure, fund_code) > 0:
                coverage["holder"] += 1
            if _count_table(db, FundManagerTenure, fund_code) > 0:
                coverage["team"] += 1
            if _count_table(db, StaticAttributionResult, fund_code) > 0:
                coverage["alpha"] += 1

    total = len(fund_codes)
    print(f"Total funds: {total}")
    for dim, count in coverage.items():
        pct = count / total * 100 if total else 0
        print(f"  {dim:<10s}: {count}/{total} ({pct:.0f}%)")

    return coverage


def main() -> None:
    fund_codes = load_sample_funds()
    print(f"Sample funds: {len(fund_codes)}")

    # Step 1: Backfill scale, holder, managers via AKShare
    dim_results = backfill_scale_and_holder_and_managers(fund_codes)

    # Step 2: Backfill static attribution (alpha dimension)
    alpha_results = backfill_static_attribution(fund_codes)

    # Step 3: Verify coverage
    coverage = verify_dimension_coverage(fund_codes)

    # Summary
    print("\n=== Backfill Summary ===")
    print(json.dumps({
        "dimensions": dim_results,
        "static_attribution": alpha_results,
        "coverage": coverage,
        "total_funds": len(fund_codes),
    }, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
