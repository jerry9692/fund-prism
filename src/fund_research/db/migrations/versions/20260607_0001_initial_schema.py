"""Initial Phase 1 schema.

Revision ID: 20260607_0001
Revises:
Create Date: 2026-06-07

"""

from collections.abc import Sequence

from alembic import op

from fund_research.db.models import Base

# revision identifiers, used by Alembic.
revision: str = "20260607_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PHASE2_TABLES = {
    "algorithm_experiment",
    "dynamic_attribution_result",
    "experiment_result",
    "reviewer_annotation",
    "scoring_backtest",
    "scoring_result",
    "simulated_holding_result",
}


def upgrade() -> None:
    """Create all Phase 1 ORM tables."""
    bind = op.get_bind()
    for table in Base.metadata.sorted_tables:
        if table.name not in PHASE2_TABLES:
            table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    """Drop all Phase 1 ORM tables."""
    bind = op.get_bind()
    for table in reversed(Base.metadata.sorted_tables):
        if table.name not in PHASE2_TABLES:
            table.drop(bind=bind, checkfirst=True)
