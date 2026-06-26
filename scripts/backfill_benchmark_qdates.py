"""Clone latest benchmark weights to fill missing quarterly dates using SQL."""
import duckdb

conn = duckdb.connect("data/fund_research.duckdb")

# Use INSERT ... SELECT with ROW_NUMBER for id generation
conn.execute("""
    CREATE TEMP TABLE bw_max_id AS SELECT COALESCE(MAX(id), 0) as mid FROM benchmark_industry_weight
""")

# Insert missing quarterly dates by cloning from the latest snapshot per benchmark
inserted = conn.execute("""
    WITH latest_snapshots AS (
        SELECT benchmark_symbol, classification_type, classification_level, MAX(snapshot_date) as max_date
        FROM benchmark_industry_weight
        GROUP BY benchmark_symbol, classification_type, classification_level
    ),
    target_dates AS (
        SELECT UNNEST([
            DATE '2022-12-31', DATE '2023-03-31', DATE '2023-06-30', DATE '2023-09-30',
            DATE '2023-12-31', DATE '2024-03-31', DATE '2024-06-30', DATE '2024-09-30',
            DATE '2024-12-31', DATE '2025-03-31', DATE '2025-06-30', DATE '2025-09-30',
            DATE '2025-12-31', DATE '2026-03-31'
        ]) as snap_date
    ),
    existing AS (
        SELECT DISTINCT benchmark_symbol, snapshot_date FROM benchmark_industry_weight
    ),
    missing_combos AS (
        SELECT ls.benchmark_symbol, ls.classification_type, ls.classification_level,
               td.snap_date, ls.max_date
        FROM latest_snapshots ls
        CROSS JOIN target_dates td
        LEFT JOIN existing e ON e.benchmark_symbol = ls.benchmark_symbol AND e.snapshot_date = td.snap_date
        WHERE e.benchmark_symbol IS NULL
    ),
    source_data AS (
        SELECT biw.benchmark_symbol, biw.classification_type, biw.classification_level,
               mc.snap_date as new_snapshot_date,
               biw.industry_code, biw.industry_name, biw.weight_pct, biw.member_count,
               biw.unmapped_weight_pct, biw.coverage_pct, biw.source_member_snapshot,
               biw.source_industry_snapshot, biw.algorithm_version, biw.warnings,
               ROW_NUMBER() OVER (ORDER BY biw.benchmark_symbol, mc.snap_date, biw.industry_code) as rn
        FROM benchmark_industry_weight biw
        JOIN missing_combos mc ON biw.benchmark_symbol = mc.benchmark_symbol
            AND biw.snapshot_date = mc.max_date
            AND biw.classification_type = mc.classification_type
            AND biw.classification_level = mc.classification_level
    )
    INSERT INTO benchmark_industry_weight
        (id, benchmark_symbol, snapshot_date, classification_type, classification_level,
         industry_code, industry_name, weight_pct, member_count, unmapped_weight_pct,
         coverage_pct, source_member_snapshot, source_industry_snapshot,
         algorithm_version, warnings, created_at)
    SELECT
        (SELECT mid FROM bw_max_id) + rn,
        benchmark_symbol, new_snapshot_date, classification_type, classification_level,
        industry_code, industry_name, weight_pct, member_count, unmapped_weight_pct,
        coverage_pct, source_member_snapshot, source_industry_snapshot,
        algorithm_version, warnings, NOW()
    FROM source_data
""").fetchone()

conn.commit()
print(f"Inserted benchmark weight rows for quarterly dates")

# Clean up temp table
conn.execute("DROP TABLE bw_max_id")

verify = conn.execute("""
    SELECT benchmark_symbol, COUNT(DISTINCT snapshot_date) as dates,
           MIN(snapshot_date), MAX(snapshot_date)
    FROM benchmark_industry_weight
    GROUP BY benchmark_symbol
""").fetchall()
for v in verify:
    print(f"  {v[0]}: {v[1]} dates ({v[2]} ~ {v[3]})")
conn.close()
