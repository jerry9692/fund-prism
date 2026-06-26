"""Check if holding industries are populated."""
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker
from fund_research.config.settings import get_settings
from fund_research.db.models import FundDisclosedHoldings
from fund_research.db.session import create_engine_from_path, init_db

settings = get_settings()
db_path = settings.db_path_absolute
init_db(db_path)
engine = create_engine_from_path(db_path)
Session = sessionmaker(bind=engine)

with Session() as db:
    total = db.query(FundDisclosedHoldings).filter(
        FundDisclosedHoldings.asset_type == "股票"
    ).count()
    with_industry = db.query(FundDisclosedHoldings).filter(
        FundDisclosedHoldings.asset_type == "股票",
        FundDisclosedHoldings.industry.isnot(None),
        FundDisclosedHoldings.industry != "",
    ).count()
    with_code = db.query(FundDisclosedHoldings).filter(
        FundDisclosedHoldings.asset_type == "股票",
        FundDisclosedHoldings.security_code.isnot(None),
    ).count()
    print(f"Total stock holdings: {total}")
    print(f"With security_code: {with_code}")
    print(f"With industry: {with_industry} ({with_industry/total*100:.1f}%)")
