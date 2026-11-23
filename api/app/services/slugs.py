"""Season slugs: the readable address of a season on the public site (/league/ffcl-s-24)."""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Season

SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
RESERVED = {"history", "new", "admin", "api", "p", "public"}  # would clash with other /league/... paths


def slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60].strip("-")
    return base or "season"


async def unique_slug(db: AsyncSession, name: str, exclude_id: int | None = None) -> str:
    base = slugify(name)
    if base in RESERVED:
        base = f"{base}-season"
    slug, n = base, 1
    while True:
        q = select(Season.id).where(Season.slug == slug)
        if exclude_id is not None:
            q = q.where(Season.id != exclude_id)
        if not await db.scalar(q):
            return slug
        n += 1
        slug = f"{base}-{n}"
