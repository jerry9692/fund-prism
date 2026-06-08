"""Database engine and initialization tests."""

from pathlib import Path

from sqlalchemy import inspect, select, text

from fund_research.db.models import FundMain
from fund_research.db.session import create_engine_from_path, get_db_url, init_db


def test_get_db_url_selects_sqlite_for_sqlite_suffix(tmp_path: Path) -> None:
    """SQLite-like suffixes should use the SQLite dialect."""
    db_path = tmp_path / "fund_research.sqlite"

    assert get_db_url(str(db_path)).startswith("sqlite:///")


def test_get_db_url_defaults_to_duckdb_for_duckdb_suffix(tmp_path: Path) -> None:
    """DuckDB remains the default local database backend."""
    db_path = tmp_path / "fund_research.duckdb"

    assert get_db_url(str(db_path)).startswith("duckdb:///")


def test_init_db_creates_core_tables_in_sqlite(tmp_path: Path) -> None:
    """The ORM metadata should initialize in SQLite."""
    db_path = tmp_path / "fund_research.sqlite"

    init_db(str(db_path))
    engine = create_engine_from_path(str(db_path))

    assert "fund_main" in inspect(engine).get_table_names()
    assert "alembic_version" in inspect(engine).get_table_names()
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == "20260607_0001"


def test_init_db_creates_core_tables_in_duckdb(tmp_path: Path) -> None:
    """The ORM metadata should initialize in DuckDB without SERIAL columns."""
    db_path = tmp_path / "fund_research.duckdb"

    init_db(str(db_path))
    engine = create_engine_from_path(str(db_path))

    assert "fund_main" in inspect(engine).get_table_names()


def test_surrogate_id_is_generated_by_application(tmp_path: Path) -> None:
    """Surrogate IDs should not rely on database autoincrement support."""
    db_path = tmp_path / "fund_research.sqlite"
    init_db(str(db_path))
    engine = create_engine_from_path(str(db_path))

    with engine.begin() as conn:
        conn.execute(
            FundMain.__table__.insert().values(
                fund_code="000001",
                short_name="测试基金",
                full_name="测试基金全称",
            )
        )
        row = conn.execute(select(FundMain.id, FundMain.fund_code)).one()

    assert row.id is not None
    assert row.fund_code == "000001"
