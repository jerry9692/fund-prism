"""Check weight coverage of existing StockDaily data against holdings."""
import duckdb
from datetime import date

conn = duckdb.connect("data/fund_research.duckdb", read_only=True)

# Get all stock codes in stock_daily
existing = set(r[0] for r in conn.execute(
    "SELECT DISTINCT stock_code FROM stock_daily WHERE LENGTH(stock_code) = 6"
).fetchall())
# Also check prefixed ones
existing_prefixed = set(r[0] for r in conn.execute(
    "SELECT DISTINCT stock_code FROM stock_daily"
).fetchall())
print(f"StockDaily 6-digit codes: {len(existing)}")
print(f"StockDaily all codes: {len(existing_prefixed)}")
print(f"Sample codes: {sorted(list(existing))[:10]}")

# Check weight coverage for each fund/report period
result = conn.execute("""
    WITH holding_stocks AS (
        SELECT fund_code, report_date, security_code, weight_pct,
               CASE WHEN security_code IN (
                   SELECT DISTINCT CASE 
                       WHEN LENGTH(stock_code)=6 THEN stock_code
                       ELSE SUBSTR(stock_code, 3)
                   END FROM stock_daily
               ) THEN 1 ELSE 0 END as has_data
        FROM fund_disclosed_holdings
        WHERE asset_type = '股票' AND security_code IS NOT NULL
    )
    SELECT fund_code, report_date,
           COUNT(*) as total_stocks,
           SUM(has_data) as covered_stocks,
           SUM(CASE WHEN has_data=1 THEN weight_pct ELSE 0 END) as covered_weight,
           SUM(weight_pct) as total_weight
    FROM holding_stocks
    GROUP BY fund_code, report_date
    ORDER BY report_date DESC
    LIMIT 20
""").fetchall()

print(f"\nWeight coverage by fund/report (latest periods):")
print(f"{'Fund':<8} {'Date':<12} {'Stocks':>8} {'Covered':>8} {'CoveredW%':>10} {'TotalW%':>10} {'CovRatio':>8}")
total_weight_covered = 0
total_weight_all = 0
for r in result:
    fc, dt, total, covered, cw, tw = r
    ratio = cw/tw*100 if tw > 0 else 0
    total_weight_covered += cw or 0
    total_weight_all += tw or 0
    print(f"{fc:<8} {str(dt):<12} {total:>8} {covered:>8} {cw:>10.2f} {tw:>10.2f} {ratio:>7.1f}%")

conn.close()
