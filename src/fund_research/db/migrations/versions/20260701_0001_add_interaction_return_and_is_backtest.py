"""add_interaction_return_and_is_backtest

Revision ID: 20260701_0001
Revises: 20260614_0001
Create Date: 2026-07-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260701_0001"
down_revision: str | None = "20260614_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "duckdb":
        interaction_exists = _duckdb_column_exists("dynamic_attribution_result", "interaction_return")
        if not interaction_exists:
            op.execute("ALTER TABLE dynamic_attribution_result ADD COLUMN interaction_return FLOAT")

        is_backtest_exists = _duckdb_column_exists("scoring_result", "is_backtest")
        if not is_backtest_exists:
            op.execute("ALTER TABLE scoring_result ADD COLUMN is_backtest BOOLEAN DEFAULT false")
    else:
        if not _column_exists("dynamic_attribution_result", "interaction_return"):
            op.add_column(
                "dynamic_attribution_result",
                sa.Column("interaction_return", sa.Float(), nullable=True),
            )
        if not _column_exists("scoring_result", "is_backtest"):
            op.add_column(
                "scoring_result",
                sa.Column("is_backtest", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "duckdb":
        op.execute("ALTER TABLE dynamic_attribution_result DROP COLUMN interaction_return")
        op.execute("ALTER TABLE scoring_result DROP COLUMN is_backtest")
    else:
        op.drop_column("dynamic_attribution_result", "interaction_return")
        op.drop_column("scoring_result", "is_backtest")


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


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns
