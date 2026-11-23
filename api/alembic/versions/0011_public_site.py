"""season slugs and public flag, player privacy

Revision ID: 0011
Revises: 0010
"""
import re
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60].strip("-") or "season"


def upgrade() -> None:
    op.add_column("seasons", sa.Column("slug", sa.String(length=100), nullable=True))
    op.add_column("seasons", sa.Column("is_public", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("seasons", sa.Column("cloned_from_id", sa.Integer(), nullable=True))
    op.create_foreign_key(op.f("fk_seasons_cloned_from_id_seasons"), "seasons", "seasons", ["cloned_from_id"], ["id"])
    op.add_column("users", sa.Column("show_publicly", sa.Boolean(), server_default="true", nullable=False))
    bind = op.get_bind()
    taken: set[str] = {"history", "new", "admin", "api", "p", "public"}
    for sid, name, status in bind.execute(sa.text("select id, name, status from seasons order by id")).all():
        base = _slug(name)
        slug, n = base, 1
        while slug in taken:
            n += 1
            slug = f"{base}-{n}"
        taken.add(slug)
        bind.execute(sa.text("update seasons set slug = :s, is_public = :p where id = :i"),
                     {"s": slug, "p": status != "draft", "i": sid})
    op.alter_column("seasons", "slug", nullable=False)
    op.create_unique_constraint(op.f("uq_seasons_slug"), "seasons", ["slug"])


def downgrade() -> None:
    op.drop_column("users", "show_publicly")
    op.drop_constraint(op.f("uq_seasons_slug"), "seasons", type_="unique")
    op.drop_constraint(op.f("fk_seasons_cloned_from_id_seasons"), "seasons", type_="foreignkey")
    op.drop_column("seasons", "cloned_from_id")
    op.drop_column("seasons", "is_public")
    op.drop_column("seasons", "slug")
