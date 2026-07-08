"""Efficient stock daily backfill - skips already-fetched stocks, uses commit batching."""
import csv
from datetime import date
from time import sleep, perf_counter
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker
from fund_research.config.settings import get_settings
from fund_research.data.adapters.akshare import AkshareAdapter
from fund_research.data.update import _apply_stock_daily_row, UpdateSummary, _snapshot_from_fetch
from fund_research.db.models import FundDisclosedHoldings, StockDaily, DataSourceSnapshot
from fund_research.db.session import create_engine_from_path, init_db

settings = get_settings()
db_path = settings.db_path_absolute
init_db(db_path)
engine = create_engine_from_path(db_path)
Session = sessionmaker(bind=engine)

START_DATE = date(2024, 1, 1)  # 与基金净值数据起点对齐，避免拉取冗余历史
BATCH_SIZE = 50
REQUEST_INTERVAL = 0.25

with Session() as db:
    existing_codes = set(r[0] for r in db.execute(
        text("SELECT DISTINCT stock_code FROM stock_daily")
    ).fetchall())
    print(f"Already have {len(existing_codes)} stocks in StockDaily")

    needed_codes = set(r[0] for r in db.execute(text("""
        SELECT DISTINCT security_code FROM fund_disclosed_holdings
        WHERE asset_type = '股票' AND security_code IS NOT NULL
    """)).fetchall())
    print(f"Need {len(needed_codes)} stocks from holdings")

    missing_codes = sorted(needed_codes - existing_codes)
    print(f"Missing: {len(missing_codes)} stocks")

adapter = AkshareAdapter()
total_inserted = 0
total_skipped = 0
errors = 0
t0 = perf_counter()

for batch_start in range(0, len(missing_codes), BATCH_SIZE):
    batch = missing_codes[batch_start:batch_start+BATCH_SIZE]
    with Session() as db:
        for i, code in enumerate(batch):
            try:
                result = adapter.fetch_stock_daily(code, start_date=START_DATE)
                _snapshot_from_fetch(db, result)
                if result.is_success and result.data is not None and not result.data.empty:
                    for row in result.data.to_dict(orient="records"):
                        action = _apply_stock_daily_row(db, row, code, dry_run=False)
                        if action == "inserted":
                            total_inserted += 1
                else:
                    total_skipped += 1
                    errors += 1
            except Exception as e:
                total_skipped += 1
                errors += 1
            if i < len(batch) - 1 and REQUEST_INTERVAL > 0:
                sleep(REQUEST_INTERVAL)
        db.commit()
    elapsed = perf_counter() - t0
    done = min(batch_start + BATCH_SIZE, len(missing_codes))
    rate = done / elapsed if elapsed > 0 else 0
    eta = (len(missing_codes) - done) / rate if rate > 0 else 0
    print(f"  Progress: {done}/{len(missing_codes)} ({done/len(missing_codes)*100:.1f}%) "
          f"inserted={total_inserted} errors={errors} ETA={eta:.0f}s")

print(f"\nDone! Inserted={total_inserted}, skipped/errors={total_skipped}")
print(f"Total time: {perf_counter()-t0:.0f}s")
