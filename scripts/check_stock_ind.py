"""Quick check: stock industry membership data."""
from sqlalchemy.orm import sessionmaker
from fund_research.config.settings import get_settings
from fund_research.db.models import StockIndustryMembership
from fund_research.db.session import create_engine_from_path, init_db

settings = get_settings()
db_path = settings.db_path_absolute
init_db(db_path)
engine = create_engine_from_path(db_path)
Session = sessionmaker(bind=engine)

with Session() as db:
    cnt = db.query(StockIndustryMembership).count()
    print(f"StockIndustryMembership rows: {cnt}")
    if cnt > 0:
        dates = db.execute(
            "SELECT DISTINCT effective_date FROM stock_industry_membership ORDER BY effective_date"
        ).fetchall()
        print(f"Effective dates: {[str(d[0]) for d in dates]}")
        levels = db.execute(
            "SELECT classification_level, COUNT(*) FROM stock_industry_membership GROUP BY classification_level"
        ).fetchall()
        print(f"By level: {[(l, c) for l, c in levels]}")
