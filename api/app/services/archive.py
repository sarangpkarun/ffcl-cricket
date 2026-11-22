"""Archived seasons are read-only. Every write route calls one of these before changing anything."""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Match, Season

ARCHIVED = "archived"


async def ensure_open(db: AsyncSession, season_id: int) -> None:
    season = await db.get(Season, season_id)
    if season is not None and season.status == ARCHIVED:
        raise HTTPException(409, "This season is archived and can no longer be changed")


async def ensure_match_open(db: AsyncSession, match: Match) -> None:
    await ensure_open(db, match.season_id)
