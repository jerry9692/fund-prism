import duckdb
conn = duckdb.connect("data/fund_research.duckdb", read_only=True)
# Check code formats in stock_daily
samples = conn.execute("""
    SELECT DISTINCT stock_code FROM stock_daily LIMIT 20
""").fetchall()
print("Sample stock_codes in StockDaily:")
for s in samples:
    print(f"  '{s[0]}'")

# Check what format the benchmark uses
idx_samples = conn.execute("""
    SELECT DISTINCT stock_code FROM stock_daily 
    WHERE stock_code LIKE 'sh000%' OR stock_code LIKE 'sh00%' OR LENGTH(stock_code) != 6
    LIMIT 10
""").fetchall()
print("\nIndex/non-6-digit codes:")
for s in idx_samples:
    print(f"  '{s[0]}'")

# Check security_code in holdings
hold_samples = conn.execute("""
    SELECT DISTINCT security_code FROM fund_disclosed_holdings
    WHERE asset_type = '股票' AND security_code IS NOT NULL
    LIMIT 10
""").fetchall()
print("\nSample security_code in holdings:")
for s in hold_samples:
    print(f"  '{s[0]}'")
conn.close()
