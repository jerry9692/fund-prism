"""Check stock code formats and data availability."""
from sqlalchemy import text, select
from sqlalchemy.orm import sessionmaker
from fund_research.config.settings import get_settings
from fund_research.db.models import FundDisclosedHoldings, StockDaily
from fund_research.db.session import create_engine_from_path, init_db

settings = get_settings()
db_path = settings.db_path_absolute
init_db(db_path)
engine = create_engine_from_path(db_path)
Session = sessionmaker(bind=engine)

with Session() as db:
    # Sample stock codes from holdings
    codes = db.execute(text("""
        SELECT DISTINCT security_code FROM fund_disclosed_holdings 
        WHERE asset_type='股票' AND security_code IS NOT NULL LIMIT 20
    """)).fetchall()
    print("Sample holding security_codes:", [c[0] for c in codes[:10]])
    
    # Sample stock codes from StockDaily
    sd_codes = db.execute(text("""
        SELECT DISTINCT stock_code FROM stock_daily LIMIT 20
    """)).fetchall()
    print("Sample StockDaily stock_codes:", [c[0] for c in sd_codes[:10]])
    
    # Check matching rate
    matched = db.execute(text("""
        SELECT COUNT(DISTINCT h.security_code)
        FROM fund_disclosed_holdings h
        WHERE h.asset_type='股票' 
          AND h.security_code IN (SELECT DISTINCT stock_code FROM stock_daily)
    """)).scalar()
    total = db.execute(text("""
        SELECT COUNT(DISTINCT security_code) FROM fund_disclosed_holdings WHERE asset_type='股票'
    """)).scalar()
    print(f"\nStock codes in holdings: {total}")
    print(f"Stock codes matched in StockDaily: {matched}")
    
    # Check index daily for 沪深300
    idx_rows = db.execute(text("""
        SELECT COUNT(*) FROM stock_daily WHERE stock_code='sh000300'
    """)).scalar()
    print(f"\nsh000300 index daily rows: {idx_rows}")
    
    # What index codes exist?
    idx_codes = db.execute(text("""
        SELECT DISTINCT stock_code FROM stock_daily WHERE stock_code LIKE 'sh%' OR stock_code LIKE 'sz%' LIMIT 20
    """)).fetchall()
    print("Index-like codes in stock_daily:", [c[0] for c in idx_codes])
