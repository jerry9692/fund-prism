"""add_data_source_to_analysis_result_tables

Revision ID: 20260702_0003
Revises: 20260702_0002
Create Date: 2026-07-02 15:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260702_0003"
down_revision: str | None = "20260702_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_ADDITIONS: list[tuple[str, str, str, bool]] = [
    ("style_exposure_result", "data_source", "VARCHAR(50)", True),
    ("style_exposure_result", "data_source_level", "VARCHAR(5)", True),
    ("style_exposure_result", "updated_at", "TIMESTAMP", True),
    ("static_attribution_result", "data_source", "VARCHAR(50)", True),
    ("static_attribution_result", "updated_at", "TIMESTAMP", True),
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
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    for table, column, sql_type, nullable in _ADDITIONS:
        if dialect == "duckdb":
            if not _duckdb_column_exists(table, column):
                op.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {sql_type}')
        else:
            if not _pg_column_exists(table, column):
                col_type = sa.String(50) if sql_type.startswith("VARCHAR") else sa.DateTime()
                if sql_type.startswith("VARCHAR") and "(5)" in sql_type:
                    col_type = sa.String(5)
                op.add_column(
                    table,
                    sa.Column(column, col_type, nullable=nullable),
                )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    for table, column, _sql_type, _nullable in reversed(_ADDITIONS):
        if dialect == "duckdb":
            try:
                op.execute(f'ALTER TABLE "{table}" DROP COLUMN "{column}"')
            except Exception:
                pass
        else:
            op.drop_column(table, column)
