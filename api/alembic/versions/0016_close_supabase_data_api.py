"""close the Supabase data API on our tables (no effect on a normal Postgres)

Revision ID: 0016
Revises: 0015
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db.lockdown import lockdown_sql

revision: str = '0016'
down_revision: str | Sequence[str] | None = '0015'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text(lockdown_sql("public")))


def downgrade() -> None:
    """Deliberately empty: reopening a data leak is never the right way back."""
