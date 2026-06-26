import duckdb
conn = duckdb.connect("data/fund_research.duckdb", read_only=True)
cnt = conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
codes = conn.execute("SELECT COUNT(DISTINCT stock_code) FROM stock_daily").fetchone()[0]
print(f"StockDaily: {cnt} rows, {codes} unique codes")
conn.close()
