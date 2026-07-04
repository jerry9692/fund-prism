"""add_experiment_id_to_simulated_holding

Revision ID: 20260704_0002
Revises: 20260704_0001
Create Date: 2026-07-04 14:00:00.000000

Adds:
- experiment_id column to simulated_holding_result (nullable FK to algorithm_experiment)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260704_0002"
down_revision: str | None = "20260704_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_column_if_missing(table_name: str, column_name: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c["name"] for c in inspector.get_columns(table_name)]

    if column_name not in columns:
        op.add_column(
            table_name,
            sa.Column(
                column_name,
                sa.BigInteger,
                sa.ForeignKey("algorithm_experiment.id"),
                nullable=True,
                index=True,
            ),
        )


def upgrade() -> None:
    _add_column_if_missing("simulated_holding_result", "experiment_id")
    _add_column_if_missing("scoring_result", "experiment_id")


def _drop_column_if_exists(table_name: str, column_name: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c["name"] for c in inspector.get_columns(table_name)]

    if column_name in columns:
        op.drop_column(table_name, column_name)


def downgrade() -> None:
    _drop_column_if_exists("simulated_holding_result", "experiment_id")
    _drop_column_if_exists("scoring_result", "experiment_id")
