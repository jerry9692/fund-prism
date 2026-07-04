"""fund_pool_and_trading_ability

Revision ID: 20260704_0001
Revises: 20260702_0003
Create Date: 2026-07-04 12:00:00.000000

Adds:
- fund_pool, fund_pool_member, saved_screen tables (P2.5-1)
- trading_ability_result table (P2.6-1)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260704_0001"
down_revision: str | None = "20260702_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    # --- P2.5-1: 基金池 ---
    if not _table_exists("fund_pool"):
        op.create_table(
            "fund_pool",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        )

    if not _table_exists("fund_pool_member"):
        op.create_table(
            "fund_pool_member",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
            sa.Column(
                "pool_id",
                sa.BigInteger,
                sa.ForeignKey("fund_pool.id"),
                nullable=False,
                index=True,
            ),
            sa.Column("fund_code", sa.String(20), nullable=False, index=True),
            sa.Column("added_at", sa.DateTime, server_default=sa.func.now()),
            sa.Column("note", sa.String(200), nullable=True),
            sa.UniqueConstraint("pool_id", "fund_code", name="uq_pool_fund"),
        )

    if not _table_exists("saved_screen"):
        op.create_table(
            "saved_screen",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("filters", sa.JSON, nullable=False),
            sa.Column("sort_by", sa.String(50), nullable=True),
            sa.Column("sort_order", sa.String(10), nullable=True),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        )

    # --- P2.6-1: 交易能力分析 ---
    if not _table_exists("trading_ability_result"):
        op.create_table(
            "trading_ability_result",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
            sa.Column("fund_code", sa.String(20), nullable=False, index=True),
            sa.Column("calc_date", sa.Date, nullable=False, index=True),
            sa.Column("algorithm_name", sa.String(50), nullable=False),
            sa.Column("algorithm_version", sa.String(10), nullable=False),
            sa.Column("period_start", sa.Date, nullable=True),
            sa.Column("period_end", sa.Date, nullable=True),
            sa.Column("estimated_turnover_rate", sa.Float, nullable=True),
            sa.Column("estimated_buy_timing_score", sa.Float, nullable=True),
            sa.Column("estimated_sell_timing_score", sa.Float, nullable=True),
            sa.Column("estimated_holding_period", sa.Float, nullable=True),
            sa.Column("estimated_excess_return_from_trading", sa.Float, nullable=True),
            sa.Column("trading_detail", sa.JSON, nullable=True),
            sa.Column("parameters", sa.JSON, nullable=True),
            sa.Column("confidence", sa.String(20), nullable=True),
            sa.Column("conclusion_status", sa.String(20), nullable=False, server_default="estimated"),
            sa.Column("warnings", sa.JSON, nullable=True),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        )


def downgrade() -> None:
    for tbl in ("trading_ability_result", "saved_screen", "fund_pool_member", "fund_pool"):
        if _table_exists(tbl):
            op.drop_table(tbl)
