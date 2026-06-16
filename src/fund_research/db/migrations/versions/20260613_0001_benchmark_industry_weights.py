"""benchmark_industry_weights

Revision ID: 20260613_0001
Revises: c775fce6a16e
Create Date: 2026-06-13 10:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260613_0001"
down_revision: str | None = "c775fce6a16e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "benchmark_index_member",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("benchmark_symbol", sa.String(length=20), nullable=False),
        sa.Column("index_code", sa.String(length=20), nullable=False),
        sa.Column("index_name", sa.String(length=100), nullable=True),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("stock_code", sa.String(length=20), nullable=False),
        sa.Column("stock_name", sa.String(length=100), nullable=True),
        sa.Column("exchange", sa.String(length=20), nullable=True),
        sa.Column("weight_pct", sa.Float(), nullable=True),
        sa.Column("source_name", sa.String(length=80), nullable=False),
        sa.Column("source_level", sa.String(length=10), nullable=False),
        sa.Column("raw_payload_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "benchmark_symbol",
            "snapshot_date",
            "stock_code",
            name="uq_benchmark_member_symbol_date_stock",
        ),
    )
    op.create_index(
        "ix_benchmark_index_member_benchmark_symbol",
        "benchmark_index_member",
        ["benchmark_symbol"],
    )
    op.create_index(
        "ix_benchmark_index_member_snapshot_date",
        "benchmark_index_member",
        ["snapshot_date"],
    )
    op.create_index(
        "ix_benchmark_index_member_stock_code",
        "benchmark_index_member",
        ["stock_code"],
    )
    op.create_index(
        "ix_benchmark_member_symbol_date",
        "benchmark_index_member",
        ["benchmark_symbol", "snapshot_date"],
    )
    op.create_index(
        "ix_benchmark_member_stock_date",
        "benchmark_index_member",
        ["stock_code", "snapshot_date"],
    )

    op.create_table(
        "stock_industry_membership",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("stock_code", sa.String(length=20), nullable=False),
        sa.Column("stock_name", sa.String(length=100), nullable=True),
        sa.Column("classification_type", sa.String(length=30), nullable=False),
        sa.Column("classification_version", sa.String(length=20), nullable=True),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("industry_code", sa.String(length=20), nullable=True),
        sa.Column("industry_name", sa.String(length=50), nullable=False),
        sa.Column("parent_industry_code", sa.String(length=20), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("source_name", sa.String(length=80), nullable=False),
        sa.Column("source_level", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "stock_code",
            "classification_type",
            "level",
            "effective_date",
            name="uq_stock_industry_stock_type_level_date",
        ),
    )
    op.create_index(
        "ix_stock_industry_membership_stock_code",
        "stock_industry_membership",
        ["stock_code"],
    )
    op.create_index(
        "ix_stock_industry_membership_classification_type",
        "stock_industry_membership",
        ["classification_type"],
    )
    op.create_index(
        "ix_stock_industry_membership_industry_name",
        "stock_industry_membership",
        ["industry_name"],
    )
    op.create_index(
        "ix_stock_industry_membership_effective_date",
        "stock_industry_membership",
        ["effective_date"],
    )
    op.create_index(
        "ix_stock_industry_stock_type_date",
        "stock_industry_membership",
        ["stock_code", "classification_type", "effective_date"],
    )
    op.create_index(
        "ix_stock_industry_type_level_name",
        "stock_industry_membership",
        ["classification_type", "level", "industry_name"],
    )

    op.create_table(
        "benchmark_industry_weight",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("benchmark_symbol", sa.String(length=20), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("classification_type", sa.String(length=30), nullable=False),
        sa.Column("classification_level", sa.Integer(), nullable=False),
        sa.Column("industry_code", sa.String(length=20), nullable=True),
        sa.Column("industry_name", sa.String(length=50), nullable=False),
        sa.Column("weight_pct", sa.Float(), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("unmapped_weight_pct", sa.Float(), nullable=True),
        sa.Column("coverage_pct", sa.Float(), nullable=True),
        sa.Column("source_member_snapshot", sa.Date(), nullable=True),
        sa.Column("source_industry_snapshot", sa.Date(), nullable=True),
        sa.Column("algorithm_version", sa.String(length=20), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "benchmark_symbol",
            "snapshot_date",
            "classification_type",
            "classification_level",
            "industry_name",
            name="uq_benchmark_industry_symbol_date_type_level_name",
        ),
    )
    op.create_index(
        "ix_benchmark_industry_weight_benchmark_symbol",
        "benchmark_industry_weight",
        ["benchmark_symbol"],
    )
    op.create_index(
        "ix_benchmark_industry_weight_snapshot_date",
        "benchmark_industry_weight",
        ["snapshot_date"],
    )
    op.create_index(
        "ix_benchmark_industry_symbol_date",
        "benchmark_industry_weight",
        ["benchmark_symbol", "snapshot_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_benchmark_industry_symbol_date", table_name="benchmark_industry_weight")
    op.drop_index("ix_benchmark_industry_weight_snapshot_date", table_name="benchmark_industry_weight")
    op.drop_index("ix_benchmark_industry_weight_benchmark_symbol", table_name="benchmark_industry_weight")
    op.drop_table("benchmark_industry_weight")

    op.drop_index("ix_stock_industry_type_level_name", table_name="stock_industry_membership")
    op.drop_index("ix_stock_industry_stock_type_date", table_name="stock_industry_membership")
    op.drop_index("ix_stock_industry_membership_effective_date", table_name="stock_industry_membership")
    op.drop_index("ix_stock_industry_membership_industry_name", table_name="stock_industry_membership")
    op.drop_index("ix_stock_industry_membership_classification_type", table_name="stock_industry_membership")
    op.drop_index("ix_stock_industry_membership_stock_code", table_name="stock_industry_membership")
    op.drop_table("stock_industry_membership")

    op.drop_index("ix_benchmark_member_stock_date", table_name="benchmark_index_member")
    op.drop_index("ix_benchmark_member_symbol_date", table_name="benchmark_index_member")
    op.drop_index("ix_benchmark_index_member_stock_code", table_name="benchmark_index_member")
    op.drop_index("ix_benchmark_index_member_snapshot_date", table_name="benchmark_index_member")
    op.drop_index("ix_benchmark_index_member_benchmark_symbol", table_name="benchmark_index_member")
    op.drop_table("benchmark_index_member")
