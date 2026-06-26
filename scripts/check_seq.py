import duckdb
conn = duckdb.connect("data/fund_research.duckdb")
# Check if there's a sequence
seqs = conn.execute("SELECT sequence_name FROM information_schema.sequences").fetchall()
print("Sequences:", seqs)
# Get max id
max_id = conn.execute("SELECT MAX(id) FROM benchmark_industry_weight").fetchone()[0]
print(f"Max id: {max_id}")
conn.close()
