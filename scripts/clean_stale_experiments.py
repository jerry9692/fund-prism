"""Clean up stale pending/running experiments by marking them as failed."""
import duckdb
from datetime import datetime

conn = duckdb.connect("data/fund_research.duckdb")
stale = conn.execute("""
    SELECT id, experiment_name, status, created_at
    FROM algorithm_experiment
    WHERE status IN ('pending', 'running')
""").fetchall()
print(f"Found {len(stale)} stale experiments")

now = datetime.now().isoformat(timespec="seconds")
updated = conn.execute("""
    UPDATE algorithm_experiment
    SET status = 'failed',
        completed_at = ?,
        summary = 'Cleaned up stale record from previous session'
    WHERE status IN ('pending', 'running')
""", [now]).fetchone()
conn.commit()
print(f"Marked {updated[0] if updated else 0} experiments as failed")

cnt = conn.execute("SELECT COUNT(*) FROM algorithm_experiment").fetchone()[0]
print(f"Total experiments in DB: {cnt}")
conn.close()
