"""add_fk_fund_pool_member

Revision ID: 20260704_0003
Revises: 20260704_0002
Create Date: 2026-07-04 16:00:00.000000

Adds:
- Foreign key constraint on fund_pool_member.pool_id -> fund_pool.id
- Alters pool_id column type from Integer to BigInteger to match fund_pool.id
"""

import contextlib
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260704_0003"
down_revision: str | None = "20260704_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK_NAME = "fk_fund_pool_member_pool_id"


def _fk_exists(table_name: str, fk_name: str) -> bool:
    """Check whether a foreign-key constraint already exists (standard SQL)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    fks = inspector.get_foreign_keys(table_name)
    return any(fk.get("name") == fk_name for fk in fks)


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


def _get_column_type(table_name: str, column_name: str) -> str | None:
    """Return the SQL type name of a column (for idempotent checks)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for col in inspector.get_columns(table_name):
        if col["name"] == column_name:
            return type(col["type"]).__name__
    return None


# ---------------------------------------------------------------------------
# Standard SQL (SQLite / PostgreSQL)
# ---------------------------------------------------------------------------

def _upgrade_standard() -> None:
    # Fix column type mismatch: fund_pool.id is BigInteger, pool_id may be Integer.
    col_type = _get_column_type("fund_pool_member", "pool_id")
    needs_type_change = col_type is not None and col_type != "BigInteger"

    with op.batch_alter_table("fund_pool_member") as batch_op:
        if needs_type_change:
            batch_op.alter_column(
                "pool_id",
                existing_type=sa.Integer(),
                type_=sa.BigInteger(),
                existing_nullable=False,
            )
        if not _fk_exists("fund_pool_member", FK_NAME):
            batch_op.create_foreign_key(
                FK_NAME,
                "fund_pool",
                ["pool_id"],
                ["id"],
            )


def _downgrade_standard() -> None:
    with op.batch_alter_table("fund_pool_member") as batch_op:
        if _fk_exists("fund_pool_member", FK_NAME):
            batch_op.drop_constraint(FK_NAME, type_="foreignkey")
        batch_op.alter_column(
            "pool_id",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=False,
        )


# ---------------------------------------------------------------------------
# DuckDB
# ---------------------------------------------------------------------------

def _upgrade_duckdb() -> None:
    import logging

    log = logging.getLogger(__name__)

    # DuckDB does not support ALTER TABLE ADD FOREIGN KEY or ALTER COLUMN TYPE
    # on existing tables in most versions.  We attempt the column type change
    # but gracefully skip the FK constraint with a warning (application-level
    # validation enforces the relationship).
    if not _duckdb_constraint_exists("fund_pool_member", FK_NAME):
        log.warning(
            "DuckDB does not support ALTER TABLE ADD FOREIGN KEY; "
            "skipping FK constraint %s on fund_pool_member "
            "(application-level validation is used instead).",
            FK_NAME,
        )

    # Best-effort column type alteration (DuckDB may or may not support this).
    with contextlib.suppress(Exception):
        op.execute(
            'ALTER TABLE "fund_pool_member" '
            'ALTER COLUMN "pool_id" TYPE BIGINT'
        )


def _downgrade_duckdb() -> None:
    if _duckdb_constraint_exists("fund_pool_member", FK_NAME):
        op.execute(f'ALTER TABLE "fund_pool_member" DROP CONSTRAINT "{FK_NAME}"')

    with contextlib.suppress(Exception):
        op.execute(
            'ALTER TABLE "fund_pool_member" '
            'ALTER COLUMN "pool_id" TYPE INTEGER'
        )
