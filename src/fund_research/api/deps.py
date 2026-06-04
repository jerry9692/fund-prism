"""FastAPI 依赖项。"""

from collections.abc import Generator

from sqlalchemy.orm import Session

from fund_research.db.session import get_db


def get_session() -> Generator[Session, None, None]:
    """获取数据库会话依赖。"""
    yield from get_db()
