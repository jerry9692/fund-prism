"""phase3_discovery_tables

Revision ID: 20260704_0004
Revises: 20260704_0003
Create Date: 2026-07-04 13:00:00.000000

Adds Phase 3 discovery & research workbench tables:
- fund_fingerprint, fingerprint_similarity_cache (P3.1)
- fund_comparison_cache (P3.2)
- anomaly_record (P3.3)
- pool_alert_rule, pool_alert_record (P3.4)
- reverse_lookup_result (P3.5)
- research_template, template_run_record (P3.6)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260704_0004"
down_revision: str | None = "20260704_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    # --- P3.1: 基金画像指纹 ---
    if not _table_exists("fund_fingerprint"):
        op.create_table(
            "fund_fingerprint",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=False),
            sa.Column("fund_code", sa.String(20), sa.ForeignKey("fund_main.fund_code"), nullable=False, index=True),
            sa.Column("calc_date", sa.Date, nullable=False, index=True),
            sa.Column("algorithm_name", sa.String(50), nullable=False),
            sa.Column("algorithm_version", sa.String(10), nullable=False),
            sa.Column("fund_type", sa.String(50), nullable=True),
            sa.Column("template_name", sa.String(50), nullable=False),
            sa.Column("vector", sa.JSON, nullable=False),
            sa.Column("vector_metadata", sa.JSON, nullable=False),
            sa.Column("missing_dimensions", sa.JSON, nullable=True),
            sa.Column("contains_estimated", sa.Boolean, nullable=False),
            sa.Column("confidence", sa.String(20), nullable=True),
            sa.Column(
                "conclusion_status",
                sa.String(20),
                nullable=False,
                server_default="computed",
            ),
            sa.Column("warnings", sa.JSON, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.UniqueConstraint(
                "fund_code",
                "calc_date",
                "algorithm_name",
                "algorithm_version",
                name="uq_fingerprint_fund_date_algo",
            ),
        )
        op.create_index(
            "ix_fingerprint_fund_date",
            "fund_fingerprint",
            ["fund_code", "calc_date"],
        )

    if not _table_exists("fingerprint_similarity_cache"):
        op.create_table(
            "fingerprint_similarity_cache",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=False),
            sa.Column("fund_code", sa.String(20), sa.ForeignKey("fund_main.fund_code"), nullable=False, index=True),
            sa.Column("metric_space", sa.String(30), nullable=False, index=True),
            sa.Column(
                "similar_fund_code", sa.String(20), sa.ForeignKey("fund_main.fund_code"), nullable=False, index=True
            ),
            sa.Column("similarity_score", sa.Float, nullable=False),
            sa.Column("contributing_dimensions", sa.JSON, nullable=False),
            sa.Column("calc_date", sa.Date, nullable=False, index=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.UniqueConstraint(
                "fund_code",
                "metric_space",
                "similar_fund_code",
                "calc_date",
                name="uq_sim_cache_fund_metric_target_date",
            ),
        )
        op.create_index(
            "ix_sim_cache_fund_metric",
            "fingerprint_similarity_cache",
            ["fund_code", "metric_space"],
        )

    # --- P3.3: 异常发现 ---
    if not _table_exists("anomaly_record"):
        op.create_table(
            "anomaly_record",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=False),
            sa.Column("fund_code", sa.String(20), sa.ForeignKey("fund_main.fund_code"), nullable=False, index=True),
            sa.Column("rule_name", sa.String(50), nullable=False, index=True),
            sa.Column("severity", sa.String(20), nullable=False, index=True),
            sa.Column("description", sa.Text, nullable=False),
            sa.Column("detail", sa.JSON, nullable=True),
            sa.Column("evidence_ids", sa.JSON, nullable=True),
            sa.Column("scope", sa.String(30), nullable=False),
            sa.Column("scope_id", sa.String(50), nullable=True),
            sa.Column(
                "conclusion_status",
                sa.String(20),
                nullable=False,
                server_default="observation",
            ),
            sa.Column(
                "detected_at", sa.DateTime, nullable=False, index=True
            ),
            sa.Column("created_at", sa.DateTime, nullable=False),
        )

    # --- P3.4: 基金池提醒 ---
    if not _table_exists("pool_alert_rule"):
        op.create_table(
            "pool_alert_rule",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=False),
            sa.Column(
                "pool_id",
                sa.BigInteger,
                sa.ForeignKey("fund_pool.id"),
                nullable=False,
                index=True,
            ),
            sa.Column("fund_code", sa.String(20), sa.ForeignKey("fund_main.fund_code"), nullable=False, index=True),
            sa.Column("alert_type", sa.String(50), nullable=False),
            sa.Column("params", sa.JSON, nullable=True),
            sa.Column("is_active", sa.Boolean, nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False),
        )

    if not _table_exists("pool_alert_record"):
        op.create_table(
            "pool_alert_record",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=False),
            sa.Column(
                "rule_id",
                sa.BigInteger,
                sa.ForeignKey("pool_alert_rule.id"),
                nullable=True,
                index=True,
            ),
            sa.Column("pool_id", sa.BigInteger, sa.ForeignKey("fund_pool.id"), nullable=False, index=True),
            sa.Column("fund_code", sa.String(20), sa.ForeignKey("fund_main.fund_code"), nullable=False, index=True),
            sa.Column("alert_type", sa.String(50), nullable=False),
            sa.Column("severity", sa.String(20), nullable=False),
            sa.Column("message", sa.Text, nullable=False),
            sa.Column("detail", sa.JSON, nullable=True),
            sa.Column(
                "triggered_at",
                sa.DateTime,
                nullable=False,
                index=True,
            ),
            sa.Column("is_read", sa.Boolean, nullable=False),
        )

    # --- P3.5: 股票反选基金 ---
    if not _table_exists("reverse_lookup_result"):
        op.create_table(
            "reverse_lookup_result",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=False),
            sa.Column(
                "stock_codes_hash", sa.String(64), nullable=False, index=True
            ),
            sa.Column("stock_codes", sa.JSON, nullable=False),
            sa.Column("fund_scope", sa.String(30), nullable=False),
            sa.Column("scope_id", sa.String(50), nullable=True),
            sa.Column("method", sa.String(20), nullable=False),
            sa.Column("time_range", sa.String(30), nullable=False),
            sa.Column("results", sa.JSON, nullable=False),
            sa.Column("stock_coverage", sa.JSON, nullable=False),
            sa.Column("calc_date", sa.Date, nullable=False, index=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
        )

    # --- P3.6: 研究任务模板 ---
    if not _table_exists("research_template"):
        op.create_table(
            "research_template",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=False),
            sa.Column(
                "template_id", sa.String(64), nullable=False, unique=True, index=True
            ),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("definition", sa.JSON, nullable=False),
            sa.Column("is_builtin", sa.Boolean, nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False),
        )

    if not _table_exists("template_run_record"):
        op.create_table(
            "template_run_record",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=False),
            sa.Column("template_id", sa.String(64), nullable=False, index=True),
            sa.Column("inputs", sa.JSON, nullable=False),
            sa.Column(
                "status", sa.String(20), nullable=False, server_default="running"
            ),
            sa.Column("steps_total", sa.Integer, server_default="0"),
            sa.Column("steps_completed", sa.Integer, server_default="0"),
            sa.Column("steps_failed", sa.Integer, server_default="0"),
            sa.Column("step_results", sa.JSON, nullable=True),
            sa.Column("research_packet_id", sa.BigInteger, nullable=True),
            sa.Column("started_at", sa.DateTime, nullable=False),
            sa.Column("completed_at", sa.DateTime, nullable=True),
            sa.Column("error_message", sa.Text, nullable=True),
        )

    # --- P3.2: 基金对比缓存 ---
    if not _table_exists("fund_comparison_cache"):
        op.create_table(
            "fund_comparison_cache",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=False),
            sa.Column(
                "fund_codes_hash", sa.String(64), nullable=False, index=True
            ),
            sa.Column("fund_codes", sa.JSON, nullable=False),
            sa.Column("dimensions", sa.JSON, nullable=False),
            sa.Column("comparison_data", sa.JSON, nullable=False),
            sa.Column("similarity_matrix", sa.JSON, nullable=True),
            sa.Column("overlap_analysis", sa.JSON, nullable=True),
            sa.Column("calc_date", sa.Date, nullable=False, index=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
        )


def downgrade() -> None:
    for tbl in (
        "fund_comparison_cache",
        "template_run_record",
        "research_template",
        "reverse_lookup_result",
        "pool_alert_record",
        "pool_alert_rule",
        "anomaly_record",
        "fingerprint_similarity_cache",
        "fund_fingerprint",
    ):
        if _table_exists(tbl):
            op.drop_table(tbl)
