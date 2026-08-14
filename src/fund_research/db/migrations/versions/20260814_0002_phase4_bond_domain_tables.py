"""phase4_bond_domain_tables

Revision ID: 20260814_0002
Revises: 20260814_0001
Create Date: 2026-08-14 18:00:00.000000

P4.1-3 债券数据域（需求书 §5.1 / §15.2）：
- bond_main         债券主表（可转债/国债/金融债/信用债）
- bond_daily        债券日行情/估值表
- yield_curve_daily 收益率曲线日序（国债/中短票 AAA/AA）
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_0002"
down_revision: str | None = "20260814_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    # --- bond_main: 债券主表 ---
    if not _table_exists("bond_main"):
        op.create_table(
            "bond_main",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=False),
            sa.Column("bond_code", sa.String(20), nullable=False, unique=True, index=True),
            sa.Column("bond_name", sa.String(100), nullable=False),
            sa.Column("bond_type", sa.String(20), nullable=False),
            sa.Column("rating", sa.String(20), nullable=True),
            sa.Column("coupon_rate", sa.Float, nullable=True),
            sa.Column("maturity_date", sa.Date, nullable=True),
            sa.Column("underlying_stock_code", sa.String(20), nullable=True),
            sa.Column("underlying_stock_name", sa.String(100), nullable=True),
            sa.Column("conversion_price", sa.Float, nullable=True),
            sa.Column("listing_date", sa.Date, nullable=True),
            sa.Column("issue_size", sa.Float, nullable=True),
            sa.Column("source_name", sa.String(80), nullable=False),
            sa.Column("source_level", sa.String(10), nullable=False),
            sa.Column("extra", sa.JSON, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
        )

    # --- bond_daily: 债券日行情/估值 ---
    if not _table_exists("bond_daily"):
        op.create_table(
            "bond_daily",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=False),
            sa.Column("bond_code", sa.String(20), nullable=False, index=True),
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
            sa.Column("extra", sa.JSON, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.UniqueConstraint("bond_code", "trade_date", name="uq_bond_code_trade_date"),
        )
        op.create_index(
            "ix_bond_daily_code_date",
            "bond_daily",
            ["bond_code", "trade_date"],
        )

    # --- yield_curve_daily: 收益率曲线日序 ---
    if not _table_exists("yield_curve_daily"):
        op.create_table(
            "yield_curve_daily",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=False),
            sa.Column("curve_name", sa.String(40), nullable=False, index=True),
            sa.Column("trade_date", sa.Date, nullable=False, index=True),
            sa.Column("tenor_years", sa.Float, nullable=False),
            sa.Column("yield_pct", sa.Float, nullable=True),
            sa.Column("source_name", sa.String(80), nullable=False),
            sa.Column("source_level", sa.String(10), nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.UniqueConstraint(
                "curve_name",
                "trade_date",
                "tenor_years",
                name="uq_yield_curve_name_date_tenor",
            ),
        )
        op.create_index(
            "ix_yield_curve_date_tenor",
            "yield_curve_daily",
            ["trade_date", "tenor_years"],
        )


def downgrade() -> None:
    op.drop_index("ix_yield_curve_date_tenor", table_name="yield_curve_daily", if_exists=True)
    op.drop_table("yield_curve_daily")
    op.drop_index("ix_bond_daily_code_date", table_name="bond_daily", if_exists=True)
    op.drop_table("bond_daily")
    op.drop_table("bond_main")
