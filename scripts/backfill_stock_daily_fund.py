"""针对单只基金补全其持仓股票的 stock_daily 行情数据。

用法：
    FUND_DB_PATH="$(pwd)/data/fund_research.sqlite" \
    uv run python scripts/backfill_stock_daily_fund.py 000001
"""
import sys
from datetime import date
from time import sleep, perf_counter

from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

from fund_research.config.settings import get_settings
from fund_research.data.adapters.akshare import AkshareAdapter
from fund_research.data.update import _apply_stock_daily_row, _snapshot_from_fetch
from fund_research.db.models import FundDisclosedHoldings, StockDaily
from fund_research.db.session import create_engine_from_path, init_db

if len(sys.argv) < 2:
    print("用法: python backfill_stock_daily_fund.py <fund_code>")
    sys.exit(1)

FUND_CODE = sys.argv[1]
START_DATE = date(2024, 1, 1)  # 与基金净值起点对齐
BATCH_COMMIT = 30
REQUEST_INTERVAL = 0.25

settings = get_settings()
db_path = settings.db_path_absolute
init_db(db_path)
engine = create_engine_from_path(db_path)
Session = sessionmaker(bind=engine)

with Session() as db:
    needed_codes = [
        r[0] for r in db.execute(text(
            "SELECT DISTINCT security_code FROM fund_disclosed_holdings "
            "WHERE fund_code = :fc AND asset_type = '股票' AND security_code IS NOT NULL "
            "ORDER BY security_code"
        ), {"fc": FUND_CODE}).fetchall()
    ]
    existing_codes = set(r[0] for r in db.execute(
        text("SELECT DISTINCT stock_code FROM stock_daily")
    ).fetchall())
    missing = sorted(set(needed_codes) - existing_codes)

print(f"[{FUND_CODE}] 持仓股票: {len(needed_codes)} 个, 已存在: {len(needed_codes) - len(missing)}, 缺失: {len(missing)}")

if not missing:
    print("无需补全")
    sys.exit(0)

adapter = AkshareAdapter()
total_inserted = 0
errors = 0
t0 = perf_counter()

for i, code in enumerate(missing):
    try:
        result = adapter.fetch_stock_daily(code, start_date=START_DATE)
        with Session() as db:
            _snapshot_from_fetch(db, result)
            if result.is_success and result.data is not None and not result.data.empty:
                for row in result.data.to_dict(orient="records"):
                    action = _apply_stock_daily_row(db, row, code, dry_run=False)
                    if action == "inserted":
                        total_inserted += 1
                db.commit()
            else:
                errors += 1
    except Exception:
        errors += 1

    if (i + 1) % 20 == 0 or i == len(missing) - 1:
        elapsed = perf_counter() - t0
        rate = (i + 1) / elapsed if elapsed > 0 else 0
        eta = (len(missing) - i - 1) / rate if rate > 0 else 0
        print(f"  Progress: {i+1}/{len(missing)} ({(i+1)/len(missing)*100:.1f}%) "
              f"inserted={total_inserted} errors={errors} ETA={eta:.0f}s")

    if i < len(missing) - 1 and REQUEST_INTERVAL > 0:
        sleep(REQUEST_INTERVAL)

print(f"\n[{FUND_CODE}] Done! Inserted={total_inserted}, errors={errors}, time={perf_counter()-t0:.0f}s")
