"""phase4_index_fund_selection_table

Revision ID: 20260820_0001
Revises: 20260817_0002
Create Date: 2026-08-20 10:00:00.000000

P4A 指数基金分析与优选（需求书 §6.2.8 / §12.4.1）：
- index_fund_selection_result  同指数分组五维评分与综合排序结果
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0001"
down_revision: str | None = "20260817_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if not _table_exists("index_fund_selection_result"):
        op.create_table(
            "index_fund_selection_result",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=False),
            sa.Column("fund_code", sa.String(20), nullable=False, index=True),
            sa.Column("calc_date", sa.Date, nullable=False, index=True),
            sa.Column("algorithm_name", sa.String(50), nullable=False),
            sa.Column("algorithm_version", sa.String(10), nullable=False),
            sa.Column("group_key", sa.String(40), nullable=True, index=True),
            sa.Column("tracking_index_code", sa.String(40), nullable=True),
            sa.Column("tracking_index_name", sa.String(100), nullable=True),
            sa.Column("template_name", sa.String(30), nullable=True),
            sa.Column("dimension_scores", sa.JSON, nullable=True),
            sa.Column("composite_score", sa.Float, nullable=True),
            sa.Column("rank_in_group", sa.Integer, nullable=True),
            sa.Column("group_size", sa.Integer, nullable=True),
            sa.Column("alpha_annualized", sa.Float, nullable=True),
            sa.Column("information_ratio", sa.Float, nullable=True),
            sa.Column("conclusion_status", sa.String(20), nullable=False, server_default="computed"),
            sa.Column("warnings", sa.JSON, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.UniqueConstraint(
                "fund_code",
                "calc_date",
                "algorithm_name",
                "algorithm_version",
                name="uq_index_fund_selection_fund_date_algo",
            ),
        )
        op.create_index(
            "ix_index_fund_selection_fund_date",
            "index_fund_selection_result",
            ["fund_code", "calc_date"],
        )


def downgrade() -> None:
    op.drop_index(
        "ix_index_fund_selection_fund_date",
        table_name="index_fund_selection_result",
        if_exists=True,
    )
    op.drop_table("index_fund_selection_result")
