"""phase4_etf_portfolio_table

Revision ID: 20260821_0003
Revises: 20260821_0002
Create Date: 2026-08-21 16:00:00.000000

P4D ETF 组合构建（需求书 §6.2.9 / §15.2 第 12 条）：
- etf_portfolio_result  组合构建结果（目标/成分权重/回测指标/约束清单/算法版本）
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260821_0003"
down_revision: str | None = "20260821_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if not _table_exists("etf_portfolio_result"):
        op.create_table(
            "etf_portfolio_result",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=False),
            sa.Column("calc_date", sa.Date, nullable=False, index=True),
            sa.Column("algorithm_name", sa.String(50), nullable=False),
            sa.Column("algorithm_version", sa.String(10), nullable=False),
            sa.Column("target_symbol", sa.String(40), nullable=False, index=True),
            sa.Column("target_name", sa.String(100), nullable=True),
            sa.Column("candidate_count", sa.Integer, nullable=True),
            sa.Column("eligible_count", sa.Integer, nullable=True),
            sa.Column("member_weights", sa.JSON, nullable=True),
            sa.Column("portfolio_stats", sa.JSON, nullable=True),
            sa.Column("backtest", sa.JSON, nullable=True),
            sa.Column("constraints", sa.JSON, nullable=True),
            sa.Column("industry_deviation", sa.JSON, nullable=True),
            sa.Column("window_start", sa.Date, nullable=True),
            sa.Column("window_end", sa.Date, nullable=True),
            sa.Column(
                "conclusion_status",
                sa.String(20),
                nullable=False,
                server_default="computed",
            ),
            sa.Column("warnings", sa.JSON, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.UniqueConstraint(
                "target_symbol",
                "calc_date",
                "algorithm_name",
                "algorithm_version",
                name="uq_etf_portfolio_target_date_algo",
            ),
        )
        op.create_index(
            "ix_etf_portfolio_target_date",
            "etf_portfolio_result",
            ["target_symbol", "calc_date"],
        )


def downgrade() -> None:
    op.drop_index(
        "ix_etf_portfolio_target_date",
        table_name="etf_portfolio_result",
        if_exists=True,
    )
    op.drop_table("etf_portfolio_result")
