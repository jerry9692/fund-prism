"""Fetch CSI 500 index members and backfill stock daily data in batches.

Usage:
    # Run batch 1 (stocks 0-49)
    python scripts/backfill_csi500_stock_daily.py --batch 1

    # Run batch 2 (stocks 50-99)
    python scripts/backfill_csi500_stock_daily.py --batch 2

    # Run all remaining at once
    python scripts/backfill_csi500_stock_daily.py --batch all

    # Check progress only
    python scripts/backfill_csi500_stock_daily.py --status
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from sqlalchemy import select  # noqa: E402

from fund_research.data.adapters.akshare import AkshareAdapter  # noqa: E402
from fund_research.data.update import upsert_akshare_stock_daily  # noqa: E402
from fund_research.db.models import StockDaily  # noqa: E402
from fund_research.db.session import get_session_factory  # noqa: E402

BATCH_SIZE = 50


CACHE_FILE = project_root / "data" / "cache" / "csi500_members.txt"


def get_csi500_members() -> set[str]:
    """Fetch CSI 500 members, with local file cache fallback."""
    adapter = AkshareAdapter()
    result = adapter.fetch_index_members("sh000905")
    if result.data is not None and not result.data.empty:
        codes = set(result.data["stock_code"].astype(str).str.zfill(6).tolist())
        # Update cache
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text("\n".join(sorted(codes)), encoding="utf-8")
        print(f"CSI 500 members fetched: {len(codes)} (cache updated)")
        return codes

    # Fallback to cache
    if CACHE_FILE.exists():
        codes = set(
            line.strip()
            for line in CACHE_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        print(f"CSI 500 members from cache: {len(codes)} (network unavailable)")
        return codes

    print("ERROR: Cannot fetch CSI 500 members and no cache available")
    return set()


def get_missing_stocks() -> list[str]:
    """Return sorted list of CSI 500 stocks missing from stock_daily."""
    csi500_codes = get_csi500_members()
    if not csi500_codes:
        return []

    session_factory = get_session_factory()
    with session_factory() as session:
        existing = set(
            session.execute(
                select(StockDaily.stock_code).distinct()
            ).scalars().all()
        )

    missing = sorted(csi500_codes - existing)
    return missing


def run_batch(batch: int) -> None:
    missing = get_missing_stocks()
    total = len(missing)
    if total == 0:
        print("All CSI 500 stocks already have daily data. Nothing to do.")
        return

    total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"Total missing: {total} stocks, {total_batches} batches of {BATCH_SIZE}")

    if batch == "all":
        batches_to_run = list(range(1, total_batches + 1))
    else:
        batch = int(batch)
        if batch < 1 or batch > total_batches:
            print(f"Invalid batch number. Valid range: 1-{total_batches}")
            return
        batches_to_run = [batch]

    session_factory = get_session_factory()

    for b in batches_to_run:
        start_idx = (b - 1) * BATCH_SIZE
        end_idx = min(start_idx + BATCH_SIZE, total)
        batch_codes = set(missing[start_idx:end_idx])

        print(f"\n{'='*60}")
        print(f"Batch {b}/{total_batches}: stocks {start_idx+1}-{end_idx} ({len(batch_codes)} stocks)")
        print(f"Codes: {sorted(batch_codes)[:5]}... ")
        print(f"{'='*60}")

        with session_factory() as session:
            summary = upsert_akshare_stock_daily(
                session,
                stock_codes=batch_codes,
                start_date=date(2020, 1, 1),
                dry_run=False,
            )

        print(f"Batch {b} done! Inserted: {summary.inserted}, "
              f"Updated: {summary.updated}, Skipped: {summary.skipped}")
        if summary.warnings:
            print(f"Warnings: {len(summary.warnings)}")
            for w in summary.warnings[:3]:
                print(f"  - {w}")

    # Show remaining
    remaining = get_missing_stocks()
    print(f"\nRemaining: {len(remaining)} stocks still missing")


def show_status() -> None:
    missing = get_missing_stocks()
    total = len(missing)
    if total == 0:
        print("All CSI 500 stocks have daily data. Complete!")
        return

    total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"Missing: {total} stocks, {total_batches} batches needed")
    print(f"Run: python scripts/backfill_csi500_stock_daily.py --batch 1")
    for i in range(total_batches):
        start = i * BATCH_SIZE
        end = min(start + BATCH_SIZE, total)
        print(f"  Batch {i+1}: stocks {start+1}-{end} ({end-start} stocks)")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--status"

    if arg == "--status":
        show_status()
    elif arg.startswith("--batch="):
        run_batch(arg.split("=", 1)[1])
    elif arg == "--batch" and len(sys.argv) > 2:
        run_batch(sys.argv[2])
    elif arg == "--batch":
        run_batch(1)
    else:
        print(f"Usage: python {sys.argv[0]} --batch N | --batch all | --status")
