"""bigint_foreign_keys

Revision ID: 20260614_0001
Revises: 20260613_0001
Create Date: 2026-06-14 10:30:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260614_0001"
down_revision: str | None = "20260613_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "duckdb":
        fund_company_type = _duckdb_column_type("fund_main", "fund_company_id")
        if fund_company_type != "BIGINT":
            op.execute("ALTER TABLE fund_main ALTER COLUMN fund_company_id SET DATA TYPE BIGINT")

        experiment_id_type = _duckdb_column_type("experiment_result", "experiment_id")
        if experiment_id_type != "BIGINT":
            op.execute("DROP INDEX IF EXISTS ix_experiment_result_experiment_id")
            op.execute(
                """
                CREATE TABLE experiment_result_new (
                    id BIGINT PRIMARY KEY,
                    experiment_id BIGINT NOT NULL,
                    fund_code VARCHAR(20) NOT NULL,
                    calc_date DATE NOT NULL,
                    is_success BOOLEAN NOT NULL DEFAULT true,
                    metrics JSON,
                    error_message TEXT,
                    warnings JSON,
                    created_at TIMESTAMP NOT NULL DEFAULT now(),
                    FOREIGN KEY (experiment_id) REFERENCES algorithm_experiment(id)
                )
                """
            )
            op.execute(
                """
                INSERT INTO experiment_result_new (
                    id,
                    experiment_id,
                    fund_code,
                    calc_date,
                    is_success,
                    metrics,
                    error_message,
                    warnings,
                    created_at
                )
                SELECT
                    id,
                    CAST(experiment_id AS BIGINT),
                    fund_code,
                    calc_date,
                    is_success,
                    metrics,
                    error_message,
                    warnings,
                    created_at
                FROM experiment_result
                """
            )
            op.execute("DROP TABLE experiment_result")
            op.execute("ALTER TABLE experiment_result_new RENAME TO experiment_result")
            op.execute(
                "CREATE INDEX ix_experiment_result_experiment_id "
                "ON experiment_result (experiment_id)"
            )


def downgrade() -> None:
    # Downgrading would risk truncating application-generated 63-bit IDs.
    pass


def _duckdb_column_type(table_name: str, column_name: str) -> str | None:
    bind = op.get_bind()
    return bind.exec_driver_sql(
        """
        SELECT data_type
        FROM information_schema.columns
        WHERE table_name = ? AND column_name = ?
        """,
        (table_name, column_name),
    ).scalar()
