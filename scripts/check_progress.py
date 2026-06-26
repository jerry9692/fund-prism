"""Check stock daily count."""
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from fund_research.config.settings import get_settings
from fund_research.db.session import create_engine_from_path, init_db
import duckdb

settings = get_settings()
db_path = settings.db_path_absolute
# Use direct duckdb to avoid locking issues
conn = duckdb.connect(str(db_path), read_only=True)
cnt = conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
codes = conn.execute("SELECT COUNT(DISTINCT stock_code) FROM stock_daily").fetchone()[0]
print(f"StockDaily: {cnt} rows, {codes} codes")
conn.close()
