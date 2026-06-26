"""Backfill historical BenchmarkIndustryWeight snapshots by cloning current weights
to key historical dates (year-end 2022-2025).

Since SW Level-1 industry weights for CSI indices change slowly, cloning the
latest snapshot to past year-end dates is a reasonable Phase-2 experiment
approximation. All cloned rows carry a warning flag noting this assumption.
"""
from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from fund_research.config.settings import get_settings
from fund_research.db.models import BenchmarkIndustryWeight
from fund_research.db.session import create_engine_from_path, init_db
import copy

settings = get_settings()
db_path = settings.db_path_absolute
init_db(db_path)
engine = create_engine_from_path(db_path)
Session = sessionmaker(bind=engine)

historical_dates = [date(2022, 12, 31), date(2023, 6, 30), date(2023, 12, 31),
                    date(2024, 6, 30), date(2024, 12, 31), date(2025, 6, 30)]

with Session() as db:
    # Get current snapshots
    current_rows = db.scalars(
        select(BenchmarkIndustryWeight)
        .order_by(BenchmarkIndustryWeight.benchmark_symbol,
                  BenchmarkIndustryWeight.snapshot_date,
                  BenchmarkIndustryWeight.industry_name)
    ).all()

    if not current_rows:
        print("ERROR: No current BenchmarkIndustryWeight rows found!")
        exit(1)

    latest_date = max(r.snapshot_date for r in current_rows)
    print(f"Latest snapshot date: {latest_date}")
    print(f"Current rows: {len(current_rows)}")

    inserted = 0
    skipped = 0
    for hist_date in historical_dates:
        for row in current_rows:
            # Check if already exists
            existing = db.scalar(
                select(BenchmarkIndustryWeight)
                .where(BenchmarkIndustryWeight.benchmark_symbol == row.benchmark_symbol)
                .where(BenchmarkIndustryWeight.snapshot_date == hist_date)
                .where(BenchmarkIndustryWeight.classification_type == row.classification_type)
                .where(BenchmarkIndustryWeight.classification_level == row.classification_level)
                .where(BenchmarkIndustryWeight.industry_name == row.industry_name)
            )
            if existing:
                skipped += 1
                continue

            new_row = BenchmarkIndustryWeight(
                benchmark_symbol=row.benchmark_symbol,
                snapshot_date=hist_date,
                classification_type=row.classification_type,
                classification_level=row.classification_level,
                industry_code=row.industry_code,
                industry_name=row.industry_name,
                weight_pct=row.weight_pct,
                member_count=row.member_count,
                unmapped_weight_pct=row.unmapped_weight_pct,
                coverage_pct=row.coverage_pct,
                source_member_snapshot=row.source_member_snapshot,
                source_industry_snapshot=row.source_industry_snapshot,
                algorithm_version=row.algorithm_version + "+historical_clone",
                warnings={"items": [f"历史快照克隆自 {latest_date}，申万一级行业权重近似，仅供Phase2实验使用"]},
            )
            db.add(new_row)
            inserted += 1
    db.commit()
    print(f"Inserted: {inserted}")
    print(f"Skipped (already exist): {skipped}")

    total = db.query(BenchmarkIndustryWeight).count()
    dates = db.execute(
        select(BenchmarkIndustryWeight.snapshot_date).distinct().order_by(BenchmarkIndustryWeight.snapshot_date)
    ).all()
    print(f"Total rows now: {total}")
    print(f"Snapshot dates: {[str(d[0]) for d in dates]}")
