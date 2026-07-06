"""drop_legacy_dynamic_attribution_columns

Revision ID: 20260706_0002
Revises: 20260706_0001
Create Date: 2026-07-06 00:02:00.000000

删除 dynamic_attribution_result 表中 ORM 已不再使用的旧版字段：
- beta_return           → 替换为 benchmark_return (BHB/BF 归因标准命名)
- sector_rotation_return → 替换为 interaction_return (BF 归因交互项)
- stock_selection_return → 替换为 selection_return (选股效应)

20260706_0001 迁移已添加新字段；本迁移删除残留旧列。
代码中已无任何对这三个字段的属性访问引用。
"""

import contextlib
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260706_0002"
down_revision: str | None = "20260706_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "dynamic_attribution_result"
_LEGACY_COLUMNS = ["beta_return", "sector_rotation_return", "stock_selection_return"]


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    for col_name in _LEGACY_COLUMNS:
        if dialect == "duckdb":
            with contextlib.suppress(Exception):
                op.execute(f'ALTER TABLE "{_TABLE}" DROP COLUMN IF EXISTS "{col_name}"')
        else:
            with contextlib.suppress(Exception):
                op.drop_column(_TABLE, col_name)


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    for col_name in reversed(_LEGACY_COLUMNS):
        if dialect == "duckdb":
            with contextlib.suppress(Exception):
                op.execute(
                    f'ALTER TABLE "{_TABLE}" ADD COLUMN "{col_name}" FLOAT'
                )
        else:
            with contextlib.suppress(Exception):
                op.add_column(_TABLE, sa.Column(col_name, sa.Float(), nullable=True))
