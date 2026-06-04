"""
Pytest 配置和共享 fixtures。

提供测试数据库、测试客户端等基础设施。
"""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from fund_research.api.app import create_app
from fund_research.db.models import Base


@pytest.fixture(scope="function")
def test_engine() -> Generator[Engine, None, None]:
    """创建测试用 SQLite 内存数据库引擎。"""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def test_session(test_engine: Engine) -> Generator[Session, None, None]:
    """创建测试数据库会话。"""
    TestSession = sessionmaker(bind=test_engine)
    session = TestSession()
    yield session
    session.close()


@pytest.fixture(scope="function")
def test_client(test_engine: Engine) -> Generator[TestClient, None, None]:
    """创建 FastAPI 测试客户端（使用测试数据库）。"""
    app = create_app()

    from fund_research.api.deps import get_session

    TestSession = sessionmaker(bind=test_engine)

    def override_get_session() -> Generator[Session, None, None]:
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
