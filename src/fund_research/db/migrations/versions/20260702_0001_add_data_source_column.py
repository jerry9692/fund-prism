"""add_data_source_column_to_phase1_tables

Revision ID: 20260702_0001
Revises: 20260701_0003
Create Date: 2026-07-02 00:00:00.000000

"""

from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision: str = "20260702_0001"
down_revision: str | None = "20260701_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_ADDITIONS: list[tuple[str, str, str, bool]] = [
    # (table_name, column_name, sql_type, nullable)
    ("fund_main", "data_source", "VARCHAR(50)", True),
    ("fund_manager_tenure", "data_source", "VARCHAR(50)", True),
    ("fund_manager_tenure", "data_source_level", "VARCHAR(20)", True),
    ("fund_manager_tenure", "updated_at", "TIMESTAMP", True),
    ("fund_nav", "data_source", "VARCHAR(50)", True),
    ("fund_scale", "data_source", "VARCHAR(50)", True),
    ("fund_scale", "data_source_level", "VARCHAR(20)", True),
    ("fund_scale", "updated_at", "TIMESTAMP", True),
    ("fund_fee", "data_source", "VARCHAR(50)", True),
    ("fund_fee", "updated_at", "TIMESTAMP", True),
    ("fund_disclosed_holdings", "data_source", "VARCHAR(50)", True),
    ("holder_structure", "data_source", "VARCHAR(50)", True),
    ("holder_structure", "updated_at", "TIMESTAMP", True),
]


def _duckdb_column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    result = bind.exec_driver_sql(
        """
        SELECT COUNT(*)
        FROM information_schema.columns
        WHERE table_name = ? AND column_name = ?
        """,
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
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()

    for table, column, sql_type, nullable in _ADDITIONS:
        if dialect == "duckdb":
            if not _duckdb_column_exists(table, column):
                null_clause = "" if nullable else "NOT NULL DEFAULT CURRENT_TIMESTAMP"
                op.execute(
                    f'ALTER TABLE "{table}" ADD COLUMN "{column}" {sql_type} {null_clause}'
                )
                if column == "updated_at":
                    op.execute(
                        f'UPDATE "{table}" SET "{column}" = ?',
                        (now,),
                    )
        else:
            if not _pg_column_exists(table, column):
                col_type = sa.String(50) if sql_type.startswith("VARCHAR") else sa.DateTime()
                if sql_type.startswith("VARCHAR") and "(20)" in sql_type:
                    col_type = sa.String(20)
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
