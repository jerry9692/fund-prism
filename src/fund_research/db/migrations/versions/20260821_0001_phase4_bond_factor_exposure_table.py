"""phase4_bond_factor_exposure_table

Revision ID: 20260821_0001
Revises: 20260820_0001
Create Date: 2026-08-21 10:00:00.000000

P4B 债基金因子暴露 · 粗粒度版（需求书 §6.2.7 / §15.2 第 11 条）：
- bond_factor_exposure_result  滚动回归因子暴露/t 值/R²/贡献拆解结果
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260821_0001"
down_revision: str | None = "20260820_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if not _table_exists("bond_factor_exposure_result"):
        op.create_table(
            "bond_factor_exposure_result",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=False),
            sa.Column("fund_code", sa.String(20), nullable=False, index=True),
            sa.Column("calc_date", sa.Date, nullable=False, index=True),
            sa.Column("algorithm_name", sa.String(50), nullable=False),
            sa.Column("algorithm_version", sa.String(10), nullable=False),
            sa.Column("template_name", sa.String(30), nullable=True),
            sa.Column("window_days", sa.Integer, nullable=True),
            sa.Column("step_days", sa.Integer, nullable=True),
            sa.Column("factor_names", sa.JSON, nullable=True),
            sa.Column("latest_exposures", sa.JSON, nullable=True),
            sa.Column("latest_t_values", sa.JSON, nullable=True),
            sa.Column("full_window_r_squared", sa.Float, nullable=True),
            sa.Column("avg_rolling_r_squared", sa.Float, nullable=True),
            sa.Column("exposure_curves", sa.JSON, nullable=True),
            sa.Column("contributions", sa.JSON, nullable=True),
            sa.Column("radar", sa.JSON, nullable=True),
            sa.Column("peer_rank", sa.JSON, nullable=True),
            sa.Column("factor_coverage", sa.JSON, nullable=True),
            sa.Column("window_start", sa.Date, nullable=True),
            sa.Column("window_end", sa.Date, nullable=True),
            sa.Column("conclusion_status", sa.String(20), nullable=False, server_default="computed"),
            sa.Column("warnings", sa.JSON, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.UniqueConstraint(
                "fund_code",
                "calc_date",
                "algorithm_name",
                "algorithm_version",
                name="uq_bond_factor_exposure_fund_date_algo",
            ),
        )
        op.create_index(
            "ix_bond_factor_exposure_fund_date",
            "bond_factor_exposure_result",
            ["fund_code", "calc_date"],
        )


def downgrade() -> None:
    op.drop_index(
        "ix_bond_factor_exposure_fund_date",
        table_name="bond_factor_exposure_result",
        if_exists=True,
    )
    op.drop_table("bond_factor_exposure_result")
