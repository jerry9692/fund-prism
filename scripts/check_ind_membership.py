"""Check stock industry membership dates and backfill industries directly."""
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from fund_research.config.settings import get_settings
from fund_research.db.models import (
    FundDisclosedHoldings, StockIndustryMembership
)
from fund_research.db.session import create_engine_from_path, init_db

settings = get_settings()
db_path = settings.db_path_absolute
init_db(db_path)
engine = create_engine_from_path(db_path)
Session = sessionmaker(bind=engine)

with Session() as db:
    # Check membership dates
    dates = db.execute(
        select(StockIndustryMembership.effective_date).distinct().order_by(StockIndustryMembership.effective_date)
    ).all()
    print(f"StockIndustryMembership effective dates: {[str(d[0]) for d in dates]}")
    cnt = db.query(StockIndustryMembership).count()
    print(f"Total membership rows: {cnt}")
    
    # Check the column name - is it 'level' or 'classification_level'?
    first = db.query(StockIndustryMembership).first()
    if first:
        print(f"First row columns: {[c.name for c in StockIndustryMembership.__table__.columns]}")
