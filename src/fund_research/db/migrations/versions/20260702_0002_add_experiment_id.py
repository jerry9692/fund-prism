"""add_experiment_id_to_phase2_result_tables

Revision ID: 20260702_0002
Revises: 20260702_0001
Create Date: 2026-07-02 00:01:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260702_0002"
down_revision: str | None = "20260702_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ["simulated_holding_result", "scoring_result", "dynamic_attribution_result"]


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
    for table in _TABLES:
        if dialect == "duckdb":
            if not _duckdb_column_exists(table, "experiment_id"):
                op.execute(f'ALTER TABLE "{table}" ADD COLUMN "experiment_id" BIGINT')
        else:
            if not _pg_column_exists(table, "experiment_id"):
                op.add_column(table, sa.Column("experiment_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    for table in reversed(_TABLES):
        if dialect == "duckdb":
            try:
                op.execute(f'ALTER TABLE "{table}" DROP COLUMN "experiment_id"')
            except Exception:
                pass
        else:
            op.drop_column(table, "experiment_id")
