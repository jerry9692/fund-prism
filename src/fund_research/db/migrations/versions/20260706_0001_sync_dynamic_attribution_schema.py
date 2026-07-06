"""sync_dynamic_attribution_result_schema

Revision ID: 20260706_0001
Revises: 20260704_0004
Create Date: 2026-07-06 00:01:00.000000

修复 dynamic_attribution_result 表结构与 ORM 不一致的问题。
c775fce6a16e 迁移创建的是旧版字段名（beta_return/sector_rotation_return/
stock_selection_return），ORM 后来重构为 BHB/BF 归因标准字段名
（benchmark_return/selection_return/interaction_return/bond_return/
cash_return/invisible_return）并新增 calc_date/is_total/
uses_simulated_holdings/benchmark_symbol 等字段，但缺少对应迁移。
"""

import contextlib
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260706_0001"
down_revision: str | None = "20260704_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "dynamic_attribution_result"

# (column_name, column_type, is_indexed)
_NEW_COLUMNS: list[tuple[str, sa.types.TypeEngine, bool]] = [
    ("calc_date", sa.Date(), True),
    ("is_total", sa.Boolean(), False),
    ("benchmark_return", sa.Float(), False),
    ("selection_return", sa.Float(), False),
    ("bond_return", sa.Float(), False),
    ("cash_return", sa.Float(), False),
    ("invisible_return", sa.Float(), False),
    ("uses_simulated_holdings", sa.Boolean(), False),
    ("benchmark_symbol", sa.String(20), False),
]


def _duckdb_column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    result = bind.exec_driver_sql(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_name = ? AND column_name = ?",
        (table_name, column_name),
    ).scalar()
    return bool(result)


def _pg_column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column_name in [c["name"] for c in inspector.get_columns(table_name)]


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    for col_name, col_type, is_indexed in _NEW_COLUMNS:
        if dialect == "duckdb":
            if not _duckdb_column_exists(_TABLE, col_name):
                op.execute(
                    f'ALTER TABLE "{_TABLE}" ADD COLUMN "{col_name}" '
                    f'{col_type.compile(dialect=bind.dialect)}'
                )
        else:
            if not _pg_column_exists(_TABLE, col_name):
                # SQLite/Postgres: nullable=True 以兼容已有行
                op.add_column(_TABLE, sa.Column(col_name, col_type, nullable=True))
        if is_indexed:
            with contextlib.suppress(Exception):
                op.create_index(
                    f"ix_{_TABLE}_{col_name}", _TABLE, [col_name]
                )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    for col_name, _col_type, is_indexed in reversed(_NEW_COLUMNS):
        if is_indexed:
            with contextlib.suppress(Exception):
                op.drop_index(f"ix_{_TABLE}_{col_name}", table_name=_TABLE)
        if dialect == "duckdb":
            with contextlib.suppress(Exception):
                op.execute(f'ALTER TABLE "{_TABLE}" DROP COLUMN "{col_name}"')
        else:
            with contextlib.suppress(Exception):
                op.drop_column(_TABLE, col_name)
