"""add_fk_enum_constraints

Revision ID: 20260701_0003
Revises: 20260701_0002
Create Date: 2026-07-01 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20260701_0003"
down_revision: str | None = "20260701_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_FK_CONSTRAINTS = [
    ("fk_fund_category_fund_code", "fund_category", "fund_code", "fund_main", "fund_code"),
    ("fk_fmt_manager_id", "fund_manager_tenure", "manager_id", "fund_manager", "manager_id"),
    ("fk_fmt_fund_code", "fund_manager_tenure", "fund_code", "fund_main", "fund_code"),
    ("fk_fund_nav_fund_code", "fund_nav", "fund_code", "fund_main", "fund_code"),
    ("fk_fund_scale_fund_code", "fund_scale", "fund_code", "fund_main", "fund_code"),
    ("fk_fund_fee_fund_code", "fund_fee", "fund_code", "fund_main", "fund_code"),
    ("fk_fdh_fund_code", "fund_disclosed_holdings", "fund_code", "fund_main", "fund_code"),
    ("fk_holder_fund_code", "holder_structure", "fund_code", "fund_main", "fund_code"),
    ("fk_stock_daily_stock_code", "stock_daily", "stock_code", "stock_main", "stock_code"),
    ("fk_ser_fund_code", "style_exposure_result", "fund_code", "fund_main", "fund_code"),
    ("fk_sar_fund_code", "static_attribution_result", "fund_code", "fund_main", "fund_code"),
    ("fk_rp_fund_code", "research_packet", "fund_code", "fund_main", "fund_code"),
    ("fk_shr_fund_code", "simulated_holding_result", "fund_code", "fund_main", "fund_code"),
    ("fk_dar_fund_code", "dynamic_attribution_result", "fund_code", "fund_main", "fund_code"),
    ("fk_sr_fund_code", "scoring_result", "fund_code", "fund_main", "fund_code"),
    ("fk_er_fund_code", "experiment_result", "fund_code", "fund_main", "fund_code"),
    ("fk_ra_fund_code", "reviewer_annotation", "fund_code", "fund_main", "fund_code"),
    ("fk_bim_stock_code", "benchmark_index_member", "stock_code", "stock_main", "stock_code"),
    ("fk_sim_stock_code", "stock_industry_membership", "stock_code", "stock_main", "stock_code"),
]

_SOURCE_LEVEL_VALUES = ("A", "B", "C", "LOCAL")
_CONFIDENCE_VALUES = ("high", "medium", "low", "needs_review")
_CONCLUSION_STATUS_VALUES = ("fact", "computed", "estimated", "observation", "needs_review")
_SOURCE_TYPE_VALUES = ("official_disclosure", "open_api", "web_scraping", "local_file", "commercial")
_TASK_TYPE_VALUES = ("data_update", "algorithm_run", "research_packet", "export")
_TASK_STATUS_VALUES = ("pending", "running", "completed", "failed", "cancelled")
_EXPERIMENT_STATUS_VALUES = ("pending", "running", "completed", "completed_with_failures", "failed", "cancelled")

_CHECK_CONSTRAINTS = [
    ("ck_fund_main_data_source_level", "fund_main", "data_source_level", _SOURCE_LEVEL_VALUES),
    ("ck_fund_nav_data_source_level", "fund_nav", "data_source_level", _SOURCE_LEVEL_VALUES),
    ("ck_fund_fee_data_source_level", "fund_fee", "data_source_level", _SOURCE_LEVEL_VALUES),
    ("ck_fdh_data_source_level", "fund_disclosed_holdings", "data_source_level", _SOURCE_LEVEL_VALUES),
    ("ck_holder_data_source_level", "holder_structure", "data_source_level", _SOURCE_LEVEL_VALUES),
    ("ck_stock_daily_data_source_level", "stock_daily", "data_source_level", _SOURCE_LEVEL_VALUES),
    ("ck_ser_confidence", "style_exposure_result", "confidence", _CONFIDENCE_VALUES),
    ("ck_ser_conclusion_status", "style_exposure_result", "conclusion_status", _CONCLUSION_STATUS_VALUES),
    ("ck_sar_confidence", "static_attribution_result", "confidence", _CONFIDENCE_VALUES),
    ("ck_sar_conclusion_status", "static_attribution_result", "conclusion_status", _CONCLUSION_STATUS_VALUES),
    ("ck_rp_overall_confidence", "research_packet", "overall_confidence", _CONFIDENCE_VALUES),
    ("ck_evidence_source_level", "evidence", "source_level", _SOURCE_LEVEL_VALUES),
    ("ck_evidence_confidence", "evidence", "confidence", _CONFIDENCE_VALUES),
    ("ck_evidence_conclusion_status", "evidence", "conclusion_status", _CONCLUSION_STATUS_VALUES),
    ("ck_dss_source_type", "data_source_snapshot", "source_type", _SOURCE_TYPE_VALUES),
    ("ck_dss_source_level", "data_source_snapshot", "source_level", _SOURCE_LEVEL_VALUES),
    ("ck_task_log_task_type", "task_log", "task_type", _TASK_TYPE_VALUES),
    ("ck_task_log_status", "task_log", "status", _TASK_STATUS_VALUES),
    ("ck_shr_confidence", "simulated_holding_result", "confidence", _CONFIDENCE_VALUES),
    ("ck_shr_conclusion_status", "simulated_holding_result", "conclusion_status", _CONCLUSION_STATUS_VALUES),
    ("ck_dar_confidence", "dynamic_attribution_result", "confidence", _CONFIDENCE_VALUES),
    ("ck_dar_conclusion_status", "dynamic_attribution_result", "conclusion_status", _CONCLUSION_STATUS_VALUES),
    ("ck_scoring_confidence", "scoring_result", "confidence", _CONFIDENCE_VALUES),
    ("ck_scoring_conclusion_status", "scoring_result", "conclusion_status", _CONCLUSION_STATUS_VALUES),
    ("ck_ae_status", "algorithm_experiment", "status", _EXPERIMENT_STATUS_VALUES),
    ("ck_bim_source_level", "benchmark_index_member", "source_level", _SOURCE_LEVEL_VALUES),
    ("ck_sim_source_level", "stock_industry_membership", "source_level", _SOURCE_LEVEL_VALUES),
]

_SERVER_DEFAULTS = [
    ("style_exposure_result", "conclusion_status", "'computed'"),
    ("static_attribution_result", "conclusion_status", "'computed'"),
    ("evidence", "confidence", "'needs_review'"),
    ("evidence", "conclusion_status", "'needs_review'"),
    ("task_log", "status", "'pending'"),
    ("simulated_holding_result", "conclusion_status", "'estimated'"),
    ("dynamic_attribution_result", "conclusion_status", "'estimated'"),
    ("scoring_result", "conclusion_status", "'computed'"),
    ("algorithm_experiment", "status", "'pending'"),
]


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "duckdb":
        _upgrade_duckdb()
    else:
        _upgrade_standard()


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "duckdb":
        _downgrade_duckdb()
    else:
        _downgrade_standard()


def _upgrade_standard() -> None:
    with op.batch_alter_table("fund_category") as batch_op:
        batch_op.create_foreign_key("fk_fund_category_fund_code", "fund_main", ["fund_code"], ["fund_code"])
    with op.batch_alter_table("fund_manager_tenure") as batch_op:
        batch_op.create_foreign_key("fk_fmt_manager_id", "fund_manager", ["manager_id"], ["manager_id"])
        batch_op.create_foreign_key("fk_fmt_fund_code", "fund_main", ["fund_code"], ["fund_code"])
    with op.batch_alter_table("fund_nav") as batch_op:
        batch_op.create_foreign_key("fk_fund_nav_fund_code", "fund_main", ["fund_code"], ["fund_code"])
    with op.batch_alter_table("fund_scale") as batch_op:
        batch_op.create_foreign_key("fk_fund_scale_fund_code", "fund_main", ["fund_code"], ["fund_code"])
    with op.batch_alter_table("fund_fee") as batch_op:
        batch_op.create_foreign_key("fk_fund_fee_fund_code", "fund_main", ["fund_code"], ["fund_code"])
    with op.batch_alter_table("fund_disclosed_holdings") as batch_op:
        batch_op.create_foreign_key("fk_fdh_fund_code", "fund_main", ["fund_code"], ["fund_code"])
    with op.batch_alter_table("holder_structure") as batch_op:
        batch_op.create_foreign_key("fk_holder_fund_code", "fund_main", ["fund_code"], ["fund_code"])
    with op.batch_alter_table("stock_daily") as batch_op:
        batch_op.create_foreign_key("fk_stock_daily_stock_code", "stock_main", ["stock_code"], ["stock_code"])
    with op.batch_alter_table("style_exposure_result") as batch_op:
        batch_op.create_foreign_key("fk_ser_fund_code", "fund_main", ["fund_code"], ["fund_code"])
    with op.batch_alter_table("static_attribution_result") as batch_op:
        batch_op.create_foreign_key("fk_sar_fund_code", "fund_main", ["fund_code"], ["fund_code"])
    with op.batch_alter_table("research_packet") as batch_op:
        batch_op.create_foreign_key("fk_rp_fund_code", "fund_main", ["fund_code"], ["fund_code"])
    with op.batch_alter_table("simulated_holding_result") as batch_op:
        batch_op.create_foreign_key("fk_shr_fund_code", "fund_main", ["fund_code"], ["fund_code"])
    with op.batch_alter_table("dynamic_attribution_result") as batch_op:
        batch_op.create_foreign_key("fk_dar_fund_code", "fund_main", ["fund_code"], ["fund_code"])
    with op.batch_alter_table("scoring_result") as batch_op:
        batch_op.create_foreign_key("fk_sr_fund_code", "fund_main", ["fund_code"], ["fund_code"])
    with op.batch_alter_table("experiment_result") as batch_op:
        batch_op.create_foreign_key("fk_er_fund_code", "fund_main", ["fund_code"], ["fund_code"])
    with op.batch_alter_table("reviewer_annotation") as batch_op:
        batch_op.create_foreign_key("fk_ra_fund_code", "fund_main", ["fund_code"], ["fund_code"])
    with op.batch_alter_table("benchmark_index_member") as batch_op:
        batch_op.create_foreign_key("fk_bim_stock_code", "stock_main", ["stock_code"], ["stock_code"])
    with op.batch_alter_table("stock_industry_membership") as batch_op:
        batch_op.create_foreign_key("fk_sim_stock_code", "stock_main", ["stock_code"], ["stock_code"])

    for cname, table, column, values in _CHECK_CONSTRAINTS:
        _create_check_constraint_standard(table, cname, column, values)

    for table, column, default_sql in _SERVER_DEFAULTS:
        _set_server_default_standard(table, column, default_sql)


def _downgrade_standard() -> None:
    for table, column, _default_sql in reversed(_SERVER_DEFAULTS):
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(column, server_default=None)

    for cname, table, _column, _values in reversed(_CHECK_CONSTRAINTS):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_constraint(cname, type_="check")

    with op.batch_alter_table("stock_industry_membership") as batch_op:
        batch_op.drop_constraint("fk_sim_stock_code", type_="foreignkey")
    with op.batch_alter_table("benchmark_index_member") as batch_op:
        batch_op.drop_constraint("fk_bim_stock_code", type_="foreignkey")
    with op.batch_alter_table("reviewer_annotation") as batch_op:
        batch_op.drop_constraint("fk_ra_fund_code", type_="foreignkey")
    with op.batch_alter_table("experiment_result") as batch_op:
        batch_op.drop_constraint("fk_er_fund_code", type_="foreignkey")
    with op.batch_alter_table("scoring_result") as batch_op:
        batch_op.drop_constraint("fk_sr_fund_code", type_="foreignkey")
    with op.batch_alter_table("dynamic_attribution_result") as batch_op:
        batch_op.drop_constraint("fk_dar_fund_code", type_="foreignkey")
    with op.batch_alter_table("simulated_holding_result") as batch_op:
        batch_op.drop_constraint("fk_shr_fund_code", type_="foreignkey")
    with op.batch_alter_table("research_packet") as batch_op:
        batch_op.drop_constraint("fk_rp_fund_code", type_="foreignkey")
    with op.batch_alter_table("static_attribution_result") as batch_op:
        batch_op.drop_constraint("fk_sar_fund_code", type_="foreignkey")
    with op.batch_alter_table("style_exposure_result") as batch_op:
        batch_op.drop_constraint("fk_ser_fund_code", type_="foreignkey")
    with op.batch_alter_table("stock_daily") as batch_op:
        batch_op.drop_constraint("fk_stock_daily_stock_code", type_="foreignkey")
    with op.batch_alter_table("holder_structure") as batch_op:
        batch_op.drop_constraint("fk_holder_fund_code", type_="foreignkey")
    with op.batch_alter_table("fund_disclosed_holdings") as batch_op:
        batch_op.drop_constraint("fk_fdh_fund_code", type_="foreignkey")
    with op.batch_alter_table("fund_fee") as batch_op:
        batch_op.drop_constraint("fk_fund_fee_fund_code", type_="foreignkey")
    with op.batch_alter_table("fund_scale") as batch_op:
        batch_op.drop_constraint("fk_fund_scale_fund_code", type_="foreignkey")
    with op.batch_alter_table("fund_nav") as batch_op:
        batch_op.drop_constraint("fk_fund_nav_fund_code", type_="foreignkey")
    with op.batch_alter_table("fund_manager_tenure") as batch_op:
        batch_op.drop_constraint("fk_fmt_fund_code", type_="foreignkey")
        batch_op.drop_constraint("fk_fmt_manager_id", type_="foreignkey")
    with op.batch_alter_table("fund_category") as batch_op:
        batch_op.drop_constraint("fk_fund_category_fund_code", type_="foreignkey")


def _upgrade_duckdb() -> None:
    for cname, table, fk_col, ref_table, ref_col in _FK_CONSTRAINTS:
        _duckdb_create_fk(cname, table, [fk_col], ref_table, [ref_col])

    for cname, table, column, values in _CHECK_CONSTRAINTS:
        _duckdb_create_check(cname, table, column, values)

    for table, column, default_sql in _SERVER_DEFAULTS:
        _duckdb_set_default(table, column, default_sql)


def _downgrade_duckdb() -> None:
    for table, column, _default_sql in reversed(_SERVER_DEFAULTS):
        _duckdb_drop_default(table, column)

    for cname, table, _column, _values in reversed(_CHECK_CONSTRAINTS):
        _duckdb_drop_constraint_if_exists(table, cname)

    for cname, table, _fk_col, _ref_table, _ref_col in reversed(_FK_CONSTRAINTS):
        _duckdb_drop_constraint_if_exists(table, cname)


def _duckdb_constraint_exists(table_name: str, constraint_name: str) -> bool:
    bind = op.get_bind()
    try:
        result = bind.exec_driver_sql(
            """
            SELECT COUNT(*)
            FROM duckdb_constraints()
            WHERE table_name = ? AND constraint_name = ?
            """,
            (table_name, constraint_name),
        ).scalar()
        return bool(result)
    except Exception:
        return False


def _duckdb_create_fk(
    constraint_name: str,
    table_name: str,
    local_cols: list[str],
    ref_table: str,
    ref_cols: list[str],
) -> None:
    if _duckdb_constraint_exists(table_name, constraint_name):
        return
    import logging
    logging.getLogger(__name__).warning(
        "DuckDB does not support ALTER TABLE ADD FOREIGN KEY; "
        "skipping FK constraint %s on %s (application-level validation is used instead).",
        constraint_name, table_name,
    )


def _duckdb_create_check(
    constraint_name: str, table_name: str, column_name: str, values: tuple[str, ...]
) -> None:
    if _duckdb_constraint_exists(table_name, constraint_name):
        return
    import logging
    logging.getLogger(__name__).warning(
        "DuckDB does not support ALTER TABLE ADD CHECK; "
        "skipping CHECK constraint %s on %s (ORM-level Enum validation is used instead).",
        constraint_name, table_name,
    )


def _duckdb_drop_constraint_if_exists(table_name: str, constraint_name: str) -> None:
    if _duckdb_constraint_exists(table_name, constraint_name):
        op.execute(f'ALTER TABLE "{table_name}" DROP CONSTRAINT "{constraint_name}"')


def _duckdb_set_default(table_name: str, column_name: str, default_sql: str) -> None:
    op.execute(
        f'ALTER TABLE "{table_name}" ALTER COLUMN "{column_name}" SET DEFAULT {default_sql}'
    )


def _duckdb_drop_default(table_name: str, column_name: str) -> None:
    op.execute(f'ALTER TABLE "{table_name}" ALTER COLUMN "{column_name}" DROP DEFAULT')


def _create_check_constraint_standard(
    table_name: str, constraint_name: str, column_name: str, values: tuple[str, ...]
) -> None:
    vals = ", ".join(f"'{v}'" for v in values)
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.create_check_constraint(
            constraint_name,
            text(f'"{column_name}" IN ({vals})'),
        )


def _set_server_default_standard(table_name: str, column_name: str, default_sql: str) -> None:
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.alter_column(column_name, server_default=text(default_sql))
