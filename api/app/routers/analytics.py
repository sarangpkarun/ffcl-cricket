"""Analytics for signed-in users: a match, a season, a team, a player."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Match, Season, Team, User
from app.db.session import get_session
from app.deps import get_current_user
from app.services import analytics as svc
from app.services.schedule import ensure_visible

router = APIRouter(tags=["analytics"])


@router.get("/matches/{match_id}/analytics")
async def match(match_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> dict:
    m = await db.get(Match, match_id)
    if not m:
        raise HTTPException(404, "Match not found")
    await ensure_visible(db, user, m)
    return await svc.match_analytics(db, m)


@router.get("/seasons/{season_id}/analytics")
async def season(season_id: int, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> dict:
    s = await db.get(Season, season_id)
    if not s:
        raise HTTPException(404, "Season not found")
    return await svc.season_analytics(db, s)


@router.get("/teams/{team_id}/analytics")
async def team(team_id: int, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> dict:
    t = await db.get(Team, team_id)
    if not t:
        raise HTTPException(404, "Team not found")
    return await svc.team_analytics(db, t)


@router.get("/players/{user_id}/analytics")
async def player(user_id: int, season_id: int | None = None, _: User = Depends(get_current_user),
                 db: AsyncSession = Depends(get_session)) -> dict:
    u = await db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Player not found")
    if season_id is not None and not await db.get(Season, season_id):
        raise HTTPException(404, "Season not found")
    return await svc.player_analytics(db, u, season_id)
