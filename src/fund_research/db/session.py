"""
数据库会话管理。

支持 DuckDB（默认）和 SQLite 两种本地后端。
通过环境变量 FUND_DB_PATH 配置路径。
"""

import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from fund_research.db.models import Base


def get_db_url(db_path: str | None = None) -> str:
    """根据路径自动选择数据库后端。

    - .duckdb 后缀 → DuckDB
    - .db / .sqlite / .sqlite3 后缀 → SQLite
    - 其他 → 默认 DuckDB
    """
    db_path = db_path or os.getenv("FUND_DB_PATH", "./data/fund_research.duckdb")

    path = Path(db_path)
    suffix = path.suffix.lower()

    if suffix in (".db", ".sqlite", ".sqlite3"):
        return f"sqlite:///{path.absolute()}"
    else:
        # DuckDB（默认）
        path.parent.mkdir(parents=True, exist_ok=True)
        # DuckDB 引擎使用 duckdb:/// 协议
        # 注意：duckdb-engine 对路径格式敏感
        abs_path = str(path.absolute()).replace("\\", "/")
        return f"duckdb:///{abs_path}"


def create_engine_from_path(db_path: str | None = None) -> Engine:
    """创建 SQLAlchemy 引擎。"""
    url = get_db_url(db_path)
    if url.startswith("duckdb://"):
        # DuckDB 不需要额外的连接参数
        return create_engine(url, echo=False)
    else:
        # SQLite
        return create_engine(
            url,
            echo=False,
            connect_args={"check_same_thread": False},
        )


# 默认引擎和会话工厂
_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """获取或创建数据库引擎（单例）。"""
    global _engine
    if _engine is None:
        _engine = create_engine_from_path()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """获取会话工厂。"""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_engine(),
        )
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：获取数据库会话（请求级别）。"""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


def init_db(db_path: str | None = None) -> None:
    """初始化数据库：创建所有表。"""
    engine = create_engine_from_path(db_path) if db_path else get_engine()
    Base.metadata.create_all(bind=engine)


def drop_db(db_path: str | None = None) -> None:
    """删除所有表（谨慎使用，仅用于测试重置）。"""
    engine = create_engine_from_path(db_path) if db_path else get_engine()
    Base.metadata.drop_all(bind=engine)


def reset_db(db_path: str | None = None) -> None:
    """重置数据库：先删除再创建。"""
    drop_db(db_path)
    init_db(db_path)
