"""phase4_index_domain_tables

Revision ID: 20260814_0001
Revises: 20260706_0002
Create Date: 2026-08-14 10:00:00.000000

P4.1-2 指数数据域（需求书 §15.2）：
- index_main        指数主表（宽基/行业/主题/风格，申万/中信/中证体系）
- index_daily       指数日行情表
- index_constituent 指数成分权重快照表
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_0001"
down_revision: str | None = "20260706_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    # --- index_main: 指数主表 ---
    if not _table_exists("index_main"):
        op.create_table(
            "index_main",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=False),
            sa.Column("index_code", sa.String(20), nullable=False, unique=True, index=True),
            sa.Column("index_name", sa.String(100), nullable=False),
            sa.Column("index_type", sa.String(20), nullable=False),
            sa.Column("classification_system", sa.String(20), nullable=False),
            sa.Column("classification_version", sa.String(20), nullable=True),
            sa.Column("level", sa.Integer, nullable=True),
            sa.Column("member_count", sa.Integer, nullable=True),
            sa.Column("source_name", sa.String(80), nullable=False),
            sa.Column("source_level", sa.String(10), nullable=False),
            sa.Column("extra", sa.JSON, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
        )

    # --- index_daily: 指数日行情 ---
    if not _table_exists("index_daily"):
        op.create_table(
            "index_daily",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=False),
            sa.Column("index_code", sa.String(20), nullable=False, index=True),
            sa.Column("trade_date", sa.Date, nullable=False, index=True),
            sa.Column("open_price", sa.Float, nullable=True),
            sa.Column("high_price", sa.Float, nullable=True),
            sa.Column("low_price", sa.Float, nullable=True),
            sa.Column("close_price", sa.Float, nullable=True),
            sa.Column("volume", sa.Float, nullable=True),
            sa.Column("amount", sa.Float, nullable=True),
            sa.Column("daily_return", sa.Float, nullable=True),
            sa.Column("source_name", sa.String(80), nullable=False),
            sa.Column("source_level", sa.String(10), nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.UniqueConstraint("index_code", "trade_date", name="uq_index_code_trade_date"),
        )
        op.create_index(
            "ix_index_daily_code_date",
            "index_daily",
            ["index_code", "trade_date"],
        )

    # --- index_constituent: 指数成分权重快照 ---
    if not _table_exists("index_constituent"):
        op.create_table(
            "index_constituent",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=False),
            sa.Column("index_code", sa.String(20), nullable=False, index=True),
            sa.Column("effective_date", sa.Date, nullable=False, index=True),
            sa.Column("stock_code", sa.String(20), nullable=False, index=True),
            sa.Column("stock_name", sa.String(100), nullable=True),
            sa.Column("weight_pct", sa.Float, nullable=True),
            sa.Column("source_name", sa.String(80), nullable=False),
            sa.Column("source_level", sa.String(10), nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.UniqueConstraint(
                "index_code",
                "effective_date",
                "stock_code",
                name="uq_index_constituent_code_date_stock",
            ),
        )
        op.create_index(
            "ix_index_constituent_code_date",
            "index_constituent",
            ["index_code", "effective_date"],
        )


def downgrade() -> None:
    op.drop_index("ix_index_constituent_code_date", table_name="index_constituent", if_exists=True)
    op.drop_table("index_constituent")
    op.drop_index("ix_index_daily_code_date", table_name="index_daily", if_exists=True)
    op.drop_table("index_daily")
    op.drop_table("index_main")
