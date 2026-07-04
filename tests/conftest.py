"""
Pytest 配置和共享 fixtures。

提供测试数据库、测试客户端等基础设施。
"""

import contextlib
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from loguru import logger
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from fund_research.api.app import create_app
from fund_research.db.models import Base


@pytest.fixture(autouse=True)
def _clear_analysis_result_tables(test_engine: Engine) -> Generator[None, None, None]:
    """每个测试前清空算法结果表,避免测试隔离问题。"""
    from sqlalchemy import text

    result_tables = [
        "simulated_holding_result",
        "dynamic_attribution_result",
        "scoring_result",
        "trading_ability_result",
        "experiment_result",
        "algorithm_experiment",
        "fund_fingerprint",
        "fingerprint_similarity_cache",
        "anomaly_record",
        "pool_alert_rule",
        "pool_alert_record",
        "reverse_lookup_result",
        "research_template",
        "template_run_record",
        "fund_comparison_cache",
    ]
    with test_engine.begin() as conn:
        for table in result_tables:
            with contextlib.suppress(Exception):
                conn.execute(text(f"DELETE FROM {table}"))
    yield


@pytest.fixture(autouse=True)
def _configure_cli_test_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Configure a consistent CLI test environment.

    1. Patches setup_logging to no-op so loguru's stderr handler is never
       added during CLI tests.
    2. Patches typer's rich_utils to use a wide, non-forced terminal so
       that Rich-formatted help output renders consistently across
       platforms (Linux CI vs local Windows), avoiding truncated option
       names and ANSI color codes mixing into result.output.
    """
    from fund_research.cli import main as cli_main

    monkeypatch.setattr(cli_main, "setup_logging", lambda *args, **kwargs: None)

    import typer.rich_utils as tru

    monkeypatch.setattr(tru, "FORCE_TERMINAL", False)
    monkeypatch.setattr(tru, "MAX_WIDTH", 200)
    monkeypatch.setattr(tru, "COLOR_SYSTEM", None)

    logger.remove()
    yield
    logger.remove()


@pytest.fixture(scope="function")
def test_engine() -> Generator[Engine, None, None]:
    """创建测试用 SQLite 内存数据库引擎。"""
    engine = create_engine(
        "sqlite://",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def test_session(test_engine: Engine) -> Generator[Session, None, None]:
    """创建测试数据库会话。"""
    test_session_factory = sessionmaker(bind=test_engine)
    session = test_session_factory()
    yield session
    session.close()


@pytest.fixture(scope="function")
def test_client(test_engine: Engine) -> Generator[TestClient, None, None]:
    """创建 FastAPI 测试客户端（使用测试数据库）。"""
    app = create_app()

    from fund_research.api.deps import get_session

    test_session_factory = sessionmaker(bind=test_engine)

    def override_get_session() -> Generator[Session, None, None]:
        session = test_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
