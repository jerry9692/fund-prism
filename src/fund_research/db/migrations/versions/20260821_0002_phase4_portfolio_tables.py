"""phase4_portfolio_tables

Revision ID: 20260821_0002
Revises: 20260821_0001
Create Date: 2026-08-21 14:00:00.000000

P4C 基金组合穿透分析与组合研究包（需求书 §6.3.9 / §12.4.2/§12.4.4）：
- fund_pool_member.weight_pct   可空组合权重（有权重=组合，无权重=观察列表）
- user_portfolio                组合分析快照（穿透/重叠/集中度）
- research_packet               entity_type/pool_id 扩展 + fund_code 可空（组合包）
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260821_0002"
down_revision: str | None = "20260821_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column_name in {c["name"] for c in inspector.get_columns(table_name)}


def upgrade() -> None:
    # 1. fund_pool_member.weight_pct（组合语义，可空向后兼容）
    if not _column_exists("fund_pool_member", "weight_pct"):
        with op.batch_alter_table("fund_pool_member") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "weight_pct",
                    sa.Float,
                    nullable=True,
                    comment="组合权重(%)，空=观察列表成员（P4C）",
                )
            )

    # 2. user_portfolio 组合分析快照
    if not _table_exists("user_portfolio"):
        op.create_table(
            "user_portfolio",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=False),
            sa.Column("pool_id", sa.BigInteger, nullable=False, index=True),
            sa.Column("calc_date", sa.Date, nullable=False, index=True),
            sa.Column("algorithm_name", sa.String(50), nullable=False),
            sa.Column("algorithm_version", sa.String(10), nullable=False),
            sa.Column("member_weights", sa.JSON, nullable=True),
            sa.Column("weights_mode", sa.String(20), nullable=True),
            sa.Column("portfolio_metrics", sa.JSON, nullable=True),
            sa.Column("correlation_matrix", sa.JSON, nullable=True),
            sa.Column("style_penetration", sa.JSON, nullable=True),
            sa.Column("industry_penetration", sa.JSON, nullable=True),
            sa.Column("holding_overlap", sa.JSON, nullable=True),
            sa.Column("concentration", sa.JSON, nullable=True),
            sa.Column("window_start", sa.Date, nullable=True),
            sa.Column("window_end", sa.Date, nullable=True),
            sa.Column("conclusion_status", sa.String(20), nullable=False, server_default="computed"),
            sa.Column("warnings", sa.JSON, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.UniqueConstraint(
                "pool_id",
                "calc_date",
                "algorithm_name",
                "algorithm_version",
                name="uq_user_portfolio_pool_date_algo",
            ),
        )
        op.create_index(
            "ix_user_portfolio_pool_date",
            "user_portfolio",
            ["pool_id", "calc_date"],
        )

    # 3. research_packet：entity_type/pool_id 扩展 + fund_code 可空
    # （SQLite/DuckDB 均需重建策略：fund_code 自带 FK，原生 ALTER 被依赖拦截）
    with op.batch_alter_table("research_packet", recreate="always") as batch_op:
        if not _column_exists("research_packet", "entity_type"):
            batch_op.add_column(
                sa.Column(
                    "entity_type",
                    sa.String(30),
                    nullable=False,
                    server_default="fund",
                    comment="实体类型 fund/portfolio（P4C）",
                )
            )
        if not _column_exists("research_packet", "pool_id"):
            batch_op.add_column(
                sa.Column("pool_id", sa.BigInteger, nullable=True)
            )
        batch_op.alter_column(
            "fund_code", existing_type=sa.String(20), nullable=True
        )
    bind = op.get_bind()
    if "ix_research_packet_pool_id" not in {
        ix["name"] for ix in sa.inspect(bind).get_indexes("research_packet")
    }:
        op.create_index(
            "ix_research_packet_pool_id", "research_packet", ["pool_id"]
        )


def downgrade() -> None:
    op.drop_index("ix_research_packet_pool_id", table_name="research_packet", if_exists=True)
    with op.batch_alter_table("research_packet", recreate="always") as batch_op:
        batch_op.alter_column("fund_code", existing_type=sa.String(20), nullable=False)
        batch_op.drop_column("pool_id")
        batch_op.drop_column("entity_type")
    op.drop_index("ix_user_portfolio_pool_date", table_name="user_portfolio", if_exists=True)
    op.drop_table("user_portfolio")
    with op.batch_alter_table("fund_pool_member") as batch_op:
        batch_op.drop_column("weight_pct")
