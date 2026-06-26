import duckdb
conn = duckdb.connect("data/fund_research.duckdb", read_only=True)
cols = conn.execute("DESCRIBE benchmark_industry_weight").fetchall()
for c in cols:
    print(c[0], c[1])
conn.close()
