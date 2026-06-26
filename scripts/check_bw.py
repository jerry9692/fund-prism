import duckdb
conn = duckdb.connect("data/fund_research.duckdb", read_only=True)

# Check benchmark weight data
print("=== BenchmarkIndustryWeight stats ===")
symbols = conn.execute("""
    SELECT benchmark_symbol, classification_type, classification_level,
           COUNT(*) as rows, COUNT(DISTINCT snapshot_date) as dates,
           MIN(snapshot_date) as min_date, MAX(snapshot_date) as max_date
    FROM benchmark_industry_weight
    GROUP BY benchmark_symbol, classification_type, classification_level
    ORDER BY benchmark_symbol
""").fetchall()
for s in symbols:
    print(f"  {s[0]} type={s[1]} lvl={s[2]} rows={s[3]} dates={s[4]} range={s[5]}~{s[6]}")

# Check coverage_pct for sh000300
print("\n=== sh000300 coverage_pct (min per snapshot) ===")
cov = conn.execute("""
    SELECT snapshot_date,
           COUNT(*) as industries,
           MIN(coverage_pct) as min_cov,
           AVG(coverage_pct) as avg_cov,
           MIN(weight_pct) as min_wt,
           SUM(weight_pct) as sum_wt
    FROM benchmark_industry_weight
    WHERE benchmark_symbol = 'sh000300'
      AND classification_type = 'SW' AND classification_level = 1
    GROUP BY snapshot_date
    ORDER BY snapshot_date
""").fetchall()
for c in cov:
    print(f"  {c[0]}: industries={c[1]} min_cov={c[2]} avg_cov={c[3]:.1f} sum_wt={c[5]:.2f}%")

# Check what report dates funds have
print("\n=== Fund holding report dates range ===")
dr = conn.execute("""
    SELECT MIN(report_date), MAX(report_date), COUNT(DISTINCT report_date)
    FROM fund_disclosed_holdings
    WHERE asset_type = '股票'
""").fetchone()
print(f"  min={dr[0]}, max={dr[1]}, count={dr[2]}")

# Check existing snapshot dates
print("\n=== sh000300 snapshot dates ===")
dates = conn.execute("""
    SELECT DISTINCT snapshot_date FROM benchmark_industry_weight
    WHERE benchmark_symbol = 'sh000300'
    ORDER BY snapshot_date
""").fetchall()
for d in dates:
    print(f"  {d[0]}")
conn.close()
