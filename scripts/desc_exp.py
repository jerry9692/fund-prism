import duckdb
conn = duckdb.connect("data/fund_research.duckdb", read_only=True)
cols = conn.execute("DESCRIBE algorithm_experiment").fetchall()
for c in cols:
    print(c[0], c[1])
conn.close()
