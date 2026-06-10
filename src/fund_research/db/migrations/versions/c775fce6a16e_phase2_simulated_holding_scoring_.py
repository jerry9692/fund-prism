"""phase2_simulated_holding_scoring_experiment

Revision ID: c775fce6a16e
Revises: 20260607_0001
Create Date: 2026-06-08 15:15:31.264713

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c775fce6a16e"
down_revision: str | None = "20260607_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop and recreate Phase 2 tables so local MVP schemas stay aligned.
    for table in ["experiment_result", "scoring_result", "scoring_backtest",
                  "reviewer_annotation", "simulated_holding_result",
                  "dynamic_attribution_result", "algorithm_experiment"]:
        op.execute(f"DROP TABLE IF EXISTS {table}")

    op.create_table(
        "algorithm_experiment",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("experiment_name", sa.String(length=100), nullable=False),
        sa.Column("algorithm_name", sa.String(length=50), nullable=False),
        sa.Column("algorithm_version", sa.String(length=10), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("sample_fund_codes", sa.JSON(), nullable=True),
        sa.Column("backtest_start", sa.Date(), nullable=True),
        sa.Column("backtest_end", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "dynamic_attribution_result",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("fund_code", sa.String(length=20), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("algorithm_name", sa.String(length=50), nullable=False),
        sa.Column("algorithm_version", sa.String(length=10), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=True),
        sa.Column("total_return", sa.Float(), nullable=True),
        sa.Column("beta_return", sa.Float(), nullable=True),
        sa.Column("allocation_return", sa.Float(), nullable=True),
        sa.Column("sector_rotation_return", sa.Float(), nullable=True),
        sa.Column("stock_selection_return", sa.Float(), nullable=True),
        sa.Column("convertible_bond_return", sa.Float(), nullable=True),
        sa.Column("ipo_return", sa.Float(), nullable=True),
        sa.Column("residual", sa.Float(), nullable=True),
        sa.Column("residual_pct", sa.Float(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.String(length=20), nullable=True),
        sa.Column("conclusion_status", sa.String(length=20), nullable=False, server_default="estimated"),
        sa.Column("warnings", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dynamic_attribution_result_fund_code", "dynamic_attribution_result", ["fund_code"])

    op.create_table(
        "experiment_result",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("experiment_id", sa.BigInteger(), nullable=False),
        sa.Column("fund_code", sa.String(length=20), nullable=False),
        sa.Column("calc_date", sa.Date(), nullable=False),
        sa.Column("is_success", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("warnings", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_experiment_result_experiment_id", "experiment_result", ["experiment_id"])

    op.create_table(
        "reviewer_annotation",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("fund_code", sa.String(length=20), nullable=False),
        sa.Column("annotation_type", sa.String(length=30), nullable=False),
        sa.Column("target_module", sa.String(length=50), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reviewer_annotation_fund_code", "reviewer_annotation", ["fund_code"])

    op.create_table(
        "scoring_backtest",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("score_version", sa.String(length=20), nullable=False),
        sa.Column("backtest_date", sa.Date(), nullable=False),
        sa.Column("group_count", sa.Integer(), nullable=False),
        sa.Column("group_results", sa.JSON(), nullable=False),
        sa.Column("monotonicity_check", sa.Boolean(), nullable=True),
        sa.Column("ic_mean", sa.Float(), nullable=True),
        sa.Column("ic_ir", sa.Float(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scoring_backtest_score_version", "scoring_backtest", ["score_version"])

    op.create_table(
        "scoring_result",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("fund_code", sa.String(length=20), nullable=False),
        sa.Column("calc_date", sa.Date(), nullable=False),
        sa.Column("score_version", sa.String(length=20), nullable=False),
        sa.Column("algorithm_version", sa.String(length=10), nullable=False),
        sa.Column("weight_config", sa.JSON(), nullable=False),
        sa.Column("total_score", sa.Float(), nullable=True),
        sa.Column("sub_scores", sa.JSON(), nullable=False),
        sa.Column("percentile_rank", sa.Float(), nullable=True),
        sa.Column("deduction_reasons", sa.JSON(), nullable=True),
        sa.Column("contains_estimated", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("confidence", sa.String(length=20), nullable=True),
        sa.Column("conclusion_status", sa.String(length=20), nullable=False, server_default="computed"),
        sa.Column("warnings", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scoring_result_fund_code", "scoring_result", ["fund_code"])

    op.create_table(
        "simulated_holding_result",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("fund_code", sa.String(length=20), nullable=False),
        sa.Column("calc_date", sa.Date(), nullable=False),
        sa.Column("algorithm_name", sa.String(length=50), nullable=False),
        sa.Column("algorithm_version", sa.String(length=10), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=True),
        sa.Column("holdings_detail", sa.JSON(), nullable=False),
        sa.Column("tracking_error", sa.Float(), nullable=True),
        sa.Column("daily_rmse", sa.Float(), nullable=True),
        sa.Column("industry_correlation", sa.Float(), nullable=True),
        sa.Column("top10_recall", sa.Float(), nullable=True),
        sa.Column("stock_weight_pct", sa.Float(), nullable=True),
        sa.Column("bond_weight_pct", sa.Float(), nullable=True),
        sa.Column("cash_weight_pct", sa.Float(), nullable=True),
        sa.Column("confidence", sa.String(length=20), nullable=True),
        sa.Column("conclusion_status", sa.String(length=20), nullable=False, server_default="estimated"),
        sa.Column("is_backtest", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("backtest_report_date", sa.Date(), nullable=True),
        sa.Column("warnings", sa.JSON(), nullable=True),
        sa.Column("input_coverage", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_simulated_holding_result_calc_date", "simulated_holding_result", ["calc_date"])
    op.create_index("ix_simulated_holding_result_fund_code", "simulated_holding_result", ["fund_code"])


def downgrade() -> None:
    op.drop_index("ix_simulated_holding_result_fund_code", table_name="simulated_holding_result")
    op.drop_index("ix_simulated_holding_result_calc_date", table_name="simulated_holding_result")
    op.drop_table("simulated_holding_result")
    op.drop_index("ix_scoring_result_fund_code", table_name="scoring_result")
    op.drop_table("scoring_result")
    op.drop_index("ix_scoring_backtest_score_version", table_name="scoring_backtest")
    op.drop_table("scoring_backtest")
    op.drop_index("ix_reviewer_annotation_fund_code", table_name="reviewer_annotation")
    op.drop_table("reviewer_annotation")
    op.drop_index("ix_experiment_result_experiment_id", table_name="experiment_result")
    op.drop_table("experiment_result")
    op.drop_index("ix_dynamic_attribution_result_fund_code", table_name="dynamic_attribution_result")
    op.drop_table("dynamic_attribution_result")
    op.drop_table("algorithm_experiment")
