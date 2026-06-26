"""Check latest dynamic attribution errors."""
import duckdb
import json

conn = duckdb.connect("data/fund_research.duckdb", read_only=True)
latest = conn.execute("""
    SELECT id, experiment_name, status, summary, created_at
    FROM algorithm_experiment
    WHERE algorithm_name = 'dynamic_attribution'
    ORDER BY created_at DESC LIMIT 1
""").fetchone()
print(f"Experiment: id={latest[0]}, name={latest[1]}, status={latest[2]}")
print(f"Summary: {latest[3]}")
print(f"Created: {latest[4]}\n")

results = conn.execute("""
    SELECT fund_code, is_success, error_message
    FROM experiment_result
    WHERE experiment_id = ?
    ORDER BY fund_code
""", [latest[0]]).fetchall()

from collections import Counter
err_counter = Counter()
for fc, is_succ, err in results:
    if not is_succ:
        short_err = (err or "no error")[:80]
        err_counter[short_err] += 1

print("Error distribution:")
for err, cnt in err_counter.most_common():
    print(f"  {cnt}: {err}")

print(f"\nFirst 5 detailed errors:")
for fc, is_succ, err in results[:5]:
    if not is_succ:
        print(f"  {fc}: {err}")
conn.close()
