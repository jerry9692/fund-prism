"""Database engine and initialization tests."""

from datetime import date
from pathlib import Path

from sqlalchemy import inspect, select, text

from fund_research.db.models import (
    BenchmarkIndexMember,
    BenchmarkIndustryWeight,
    FundMain,
    StockIndustryMembership,
)
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

    table_names = inspect(engine).get_table_names()
    assert "fund_main" in table_names
    assert "benchmark_index_member" in table_names
    assert "stock_industry_membership" in table_names
    assert "benchmark_industry_weight" in table_names
    assert "alembic_version" in table_names
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == "20260613_0001"


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


def test_benchmark_industry_models_round_trip(tmp_path: Path) -> None:
    """Benchmark industry schema should persist member, industry, and aggregate rows."""
    db_path = tmp_path / "fund_research.sqlite"
    init_db(str(db_path))
    engine = create_engine_from_path(str(db_path))

    snapshot_date = date(2026, 6, 1)
    with engine.begin() as conn:
        conn.execute(
            BenchmarkIndexMember.__table__.insert().values(
                benchmark_symbol="sh000300",
                index_code="000300",
                index_name="沪深300",
                snapshot_date=snapshot_date,
                stock_code="600519",
                stock_name="贵州茅台",
                exchange="SH",
                weight_pct=5.25,
                source_name="akshare.index_stock_cons_weight_csindex",
                source_level="B",
                raw_payload_hash="abc123",
            )
        )
        conn.execute(
            StockIndustryMembership.__table__.insert().values(
                stock_code="600519",
                stock_name="贵州茅台",
                classification_type="SW",
                classification_version="2021",
                level=1,
                industry_code="801120",
                industry_name="食品饮料",
                parent_industry_code=None,
                effective_date=snapshot_date,
                source_name="akshare.sw_index_third_cons",
                source_level="C",
            )
        )
        conn.execute(
            BenchmarkIndustryWeight.__table__.insert().values(
                benchmark_symbol="sh000300",
                snapshot_date=snapshot_date,
                classification_type="SW",
                classification_level=1,
                industry_code="801120",
                industry_name="食品饮料",
                weight_pct=12.5,
                member_count=15,
                unmapped_weight_pct=0.5,
                coverage_pct=99.5,
                source_member_snapshot=snapshot_date,
                source_industry_snapshot=snapshot_date,
                algorithm_version="benchmark_industry_weight:0.1.0",
                warnings={"items": ["sample"]},
            )
        )

        member_weight = conn.execute(
            select(BenchmarkIndexMember.weight_pct).where(BenchmarkIndexMember.stock_code == "600519")
        ).scalar_one()
        industry_weight = conn.execute(
            select(BenchmarkIndustryWeight.coverage_pct, BenchmarkIndustryWeight.warnings).where(
                BenchmarkIndustryWeight.benchmark_symbol == "sh000300"
            )
        ).one()

    assert member_weight == 5.25
    assert industry_weight.coverage_pct == 99.5
    assert industry_weight.warnings == {"items": ["sample"]}
