"""Bulk backfill holding industries using set-based query."""
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from fund_research.config.settings import get_settings
from fund_research.db.session import create_engine_from_path, init_db

settings = get_settings()
db_path = settings.db_path_absolute
init_db(db_path)
engine = create_engine_from_path(db_path)
Session = sessionmaker(bind=engine)

with Session() as db:
    # First reset any partial updates
    result = db.execute(text("""
        UPDATE fund_disclosed_holdings
        SET industry = (
            SELECT sim.industry_name
            FROM stock_industry_membership sim
            WHERE sim.stock_code = fund_disclosed_holdings.security_code
              AND sim.classification_type = 'SW'
              AND sim.level = 1
              AND sim.effective_date <= fund_disclosed_holdings.report_date
            ORDER BY sim.effective_date DESC
            LIMIT 1
        )
        WHERE fund_disclosed_holdings.asset_type = '股票'
          AND fund_disclosed_holdings.security_code IS NOT NULL
    """))
    db.commit()
    print(f"Updated {result.rowcount} holdings with industry names")
    
    total = db.execute(text("""
        SELECT COUNT(*) FROM fund_disclosed_holdings
        WHERE asset_type = '股票' AND security_code IS NOT NULL
    """)).scalar()
    with_ind = db.execute(text("""
        SELECT COUNT(*) FROM fund_disclosed_holdings
        WHERE asset_type = '股票' AND security_code IS NOT NULL AND industry IS NOT NULL AND industry != ''
    """)).scalar()
    missing = db.execute(text("""
        SELECT COUNT(*) FROM fund_disclosed_holdings
        WHERE asset_type = '股票' AND security_code IS NOT NULL AND (industry IS NULL OR industry = '')
    """)).scalar()
    print(f"Total: {total}, With industry: {with_ind} ({with_ind/total*100:.1f}%), Missing: {missing}")
