"""phase4_factor_return_table

Revision ID: 20260817_0002
Revises: 20260817_0001
Create Date: 2026-08-17 16:00:00.000000

P4.1-5 因子收益表（需求书 §15.2 / §6.2.7）：
- factor_return  因子日收益序列（风格因子 + 债券因子）
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260817_0002"
down_revision: str | None = "20260817_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if not _table_exists("factor_return"):
        op.create_table(
            "factor_return",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=False),
            sa.Column("factor_name", sa.String(40), nullable=False, index=True),
            sa.Column("trade_date", sa.Date, nullable=False, index=True),
            sa.Column("factor_return", sa.Float, nullable=True),
            sa.Column("source_name", sa.String(80), nullable=False),
            sa.Column("source_level", sa.String(10), nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.UniqueConstraint("factor_name", "trade_date", name="uq_factor_name_trade_date"),
        )
        op.create_index(
            "ix_factor_return_name_date",
            "factor_return",
            ["factor_name", "trade_date"],
        )


def downgrade() -> None:
    op.drop_index("ix_factor_return_name_date", table_name="factor_return", if_exists=True)
    op.drop_table("factor_return")
