"""phase4_etf_profile_table

Revision ID: 20260817_0001
Revises: 20260814_0002
Create Date: 2026-08-17 10:00:00.000000

P4.1-4 ETF 产品属性（需求书 §6.2.8 评价维度）：
- etf_profile  ETF 产品属性快照（流动性/折溢价/跟踪误差/超额）
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260817_0001"
down_revision: str | None = "20260814_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if not _table_exists("etf_profile"):
        op.create_table(
            "etf_profile",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=False),
            sa.Column("fund_code", sa.String(20), nullable=False, unique=True, index=True),
            sa.Column("fund_name", sa.String(100), nullable=True),
            sa.Column("tracking_index_code", sa.String(20), nullable=True),
            sa.Column("tracking_index_name", sa.String(100), nullable=True),
            sa.Column("inception_date", sa.Date, nullable=True),
            sa.Column("avg_daily_amount_1y", sa.Float, nullable=True),
            sa.Column("avg_daily_turnover_1y", sa.Float, nullable=True),
            sa.Column("latest_premium_rate", sa.Float, nullable=True),
            sa.Column("tracking_error_1y", sa.Float, nullable=True),
            sa.Column("tracking_error_inception", sa.Float, nullable=True),
            sa.Column("annualized_excess_1y", sa.Float, nullable=True),
            sa.Column("annualized_excess_inception", sa.Float, nullable=True),
            sa.Column("snapshot_date", sa.Date, nullable=True),
            sa.Column("source_name", sa.String(80), nullable=False),
            sa.Column("source_level", sa.String(10), nullable=False),
            sa.Column("extra", sa.JSON, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
        )


def downgrade() -> None:
    op.drop_table("etf_profile")
