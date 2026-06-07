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


def upgrade() -> None:
    """Create all Phase 1 ORM tables."""
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    """Drop all Phase 1 ORM tables."""
    Base.metadata.drop_all(bind=op.get_bind())
