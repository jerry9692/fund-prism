"""Check which benchmarks sample funds use."""
import csv
from sqlalchemy.orm import sessionmaker
from fund_research.config.settings import get_settings
from fund_research.db.models import FundMain
from fund_research.db.session import create_engine_from_path, init_db

settings = get_settings()
db_path = settings.db_path_absolute
init_db(db_path)
engine = create_engine_from_path(db_path)
Session = sessionmaker(bind=engine)

benchmarks = {}
with Session() as db:
    funds = db.query(FundMain).all()
    for f in funds:
        b = f.benchmark or "无"
        benchmarks[b] = benchmarks.get(b, 0) + 1

print("=== Fund Benchmark Distribution ===")
for b, n in sorted(benchmarks.items(), key=lambda x: -x[1]):
    print(f"  {n:3d}x  {b}")
