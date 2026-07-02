"""add_unique_constraints_phase2

Revision ID: 20260701_0002
Revises: 20260701_0001
Create Date: 2026-07-01 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260701_0002"
down_revision: str | None = "20260701_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
    with op.batch_alter_table("simulated_holding_result") as batch_op:
        batch_op.create_unique_constraint(
            "uq_sim_holding_fund_date_algo",
            ["fund_code", "calc_date", "algorithm_name", "algorithm_version"],
        )
    op.create_index(
        "ix_sim_holding_fund_date_algo",
        "simulated_holding_result",
        ["fund_code", "calc_date", "algorithm_name"],
    )

    with op.batch_alter_table("dynamic_attribution_result") as batch_op:
        batch_op.create_unique_constraint(
            "uq_dyn_attr_fund_period_algo",
            ["fund_code", "period_start", "period_end", "algorithm_name", "algorithm_version"],
        )
    op.create_index(
        "ix_dyn_attr_fund_period",
        "dynamic_attribution_result",
        ["fund_code", "period_start", "period_end"],
    )

    with op.batch_alter_table("scoring_result") as batch_op:
        batch_op.create_unique_constraint(
            "uq_scoring_fund_date_version",
            ["fund_code", "calc_date", "score_version", "algorithm_version", "is_backtest"],
        )
    op.create_index(
        "ix_scoring_fund_date_version",
        "scoring_result",
        ["fund_code", "calc_date", "score_version"],
    )

    with op.batch_alter_table("scoring_backtest") as batch_op:
        batch_op.create_unique_constraint(
            "uq_scoring_bt_version_date",
            ["score_version", "backtest_date"],
        )
    op.create_index(
        "ix_scoring_bt_version_date",
        "scoring_backtest",
        ["score_version", "backtest_date"],
    )

    with op.batch_alter_table("experiment_result") as batch_op:
        batch_op.create_unique_constraint(
            "uq_exp_result_exp_fund_date",
            ["experiment_id", "fund_code", "calc_date"],
        )
    op.create_index(
        "ix_exp_result_exp_fund_date",
        "experiment_result",
        ["experiment_id", "fund_code", "calc_date"],
    )


def _downgrade_standard() -> None:
    op.drop_index("ix_exp_result_exp_fund_date", table_name="experiment_result")
    with op.batch_alter_table("experiment_result") as batch_op:
        batch_op.drop_constraint("uq_exp_result_exp_fund_date", type_="unique")

    op.drop_index("ix_scoring_bt_version_date", table_name="scoring_backtest")
    with op.batch_alter_table("scoring_backtest") as batch_op:
        batch_op.drop_constraint("uq_scoring_bt_version_date", type_="unique")

    op.drop_index("ix_scoring_fund_date_version", table_name="scoring_result")
    with op.batch_alter_table("scoring_result") as batch_op:
        batch_op.drop_constraint("uq_scoring_fund_date_version", type_="unique")

    op.drop_index("ix_dyn_attr_fund_period", table_name="dynamic_attribution_result")
    with op.batch_alter_table("dynamic_attribution_result") as batch_op:
        batch_op.drop_constraint("uq_dyn_attr_fund_period_algo", type_="unique")

    op.drop_index("ix_sim_holding_fund_date_algo", table_name="simulated_holding_result")
    with op.batch_alter_table("simulated_holding_result") as batch_op:
        batch_op.drop_constraint("uq_sim_holding_fund_date_algo", type_="unique")


def _upgrade_duckdb() -> None:
    _duckdb_create_unique_constraint(
        "uq_sim_holding_fund_date_algo",
        "simulated_holding_result",
        ["fund_code", "calc_date", "algorithm_name", "algorithm_version"],
    )
    _duckdb_create_index(
        "ix_sim_holding_fund_date_algo",
        "simulated_holding_result",
        ["fund_code", "calc_date", "algorithm_name"],
    )

    _duckdb_create_unique_constraint(
        "uq_dyn_attr_fund_period_algo",
        "dynamic_attribution_result",
        ["fund_code", "period_start", "period_end", "algorithm_name", "algorithm_version"],
    )
    _duckdb_create_index(
        "ix_dyn_attr_fund_period",
        "dynamic_attribution_result",
        ["fund_code", "period_start", "period_end"],
    )

    _duckdb_create_unique_constraint(
        "uq_scoring_fund_date_version",
        "scoring_result",
        ["fund_code", "calc_date", "score_version", "algorithm_version", "is_backtest"],
    )
    _duckdb_create_index(
        "ix_scoring_fund_date_version",
        "scoring_result",
        ["fund_code", "calc_date", "score_version"],
    )

    _duckdb_create_unique_constraint(
        "uq_scoring_bt_version_date",
        "scoring_backtest",
        ["score_version", "backtest_date"],
    )
    _duckdb_create_index(
        "ix_scoring_bt_version_date",
        "scoring_backtest",
        ["score_version", "backtest_date"],
    )

    _duckdb_create_unique_constraint(
        "uq_exp_result_exp_fund_date",
        "experiment_result",
        ["experiment_id", "fund_code", "calc_date"],
    )
    _duckdb_create_index(
        "ix_exp_result_exp_fund_date",
        "experiment_result",
        ["experiment_id", "fund_code", "calc_date"],
    )


def _downgrade_duckdb() -> None:
    _duckdb_drop_index_if_exists("ix_exp_result_exp_fund_date")
    _duckdb_drop_constraint_if_exists("experiment_result", "uq_exp_result_exp_fund_date")

    _duckdb_drop_index_if_exists("ix_scoring_bt_version_date")
    _duckdb_drop_constraint_if_exists("scoring_backtest", "uq_scoring_bt_version_date")

    _duckdb_drop_index_if_exists("ix_scoring_fund_date_version")
    _duckdb_drop_constraint_if_exists("scoring_result", "uq_scoring_fund_date_version")

    _duckdb_drop_index_if_exists("ix_dyn_attr_fund_period")
    _duckdb_drop_constraint_if_exists("dynamic_attribution_result", "uq_dyn_attr_fund_period_algo")

    _duckdb_drop_index_if_exists("ix_sim_holding_fund_date_algo")
    _duckdb_drop_constraint_if_exists("simulated_holding_result", "uq_sim_holding_fund_date_algo")


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


def _duckdb_index_exists(index_name: str) -> bool:
    bind = op.get_bind()
    try:
        result = bind.exec_driver_sql(
            """
            SELECT COUNT(*)
            FROM duckdb_indexes()
            WHERE index_name = ?
            """,
            (index_name,),
        ).scalar()
        return bool(result)
    except Exception:
        return False


def _duckdb_create_unique_constraint(
    constraint_name: str, table_name: str, columns: list[str]
) -> None:
    if _duckdb_constraint_exists(table_name, constraint_name):
        return
    import logging
    logging.getLogger(__name__).warning(
        "DuckDB does not support ALTER TABLE ADD CONSTRAINT UNIQUE; "
        "skipping constraint %s on %s (application-level deduplication is used instead).",
        constraint_name, table_name,
    )


def _duckdb_create_index(index_name: str, table_name: str, columns: list[str]) -> None:
    if _duckdb_index_exists(index_name):
        return
    cols = ", ".join(f'"{c}"' for c in columns)
    op.execute(f'CREATE INDEX "{index_name}" ON "{table_name}" ({cols})')


def _duckdb_drop_index_if_exists(index_name: str) -> None:
    if _duckdb_index_exists(index_name):
        op.execute(f'DROP INDEX "{index_name}"')


def _duckdb_drop_constraint_if_exists(table_name: str, constraint_name: str) -> None:
    if _duckdb_constraint_exists(table_name, constraint_name):
        op.execute(
            f'ALTER TABLE "{table_name}" DROP CONSTRAINT "{constraint_name}"'
        )
