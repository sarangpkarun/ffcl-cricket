"""Read model for a match: header, toss, current over (privacy-filtered) and scorecard."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Match, User
from app.db.session import get_session
from app.deps import get_current_user
from app.services.live_view import build_live
from app.services.schedule import ensure_visible

router = APIRouter(tags=["live"])


@router.get("/matches/{match_id}/live")
async def live(match_id: int, user: User = Depends(get_current_user),
               db: AsyncSession = Depends(get_session)) -> dict:
    m = await db.get(Match, match_id)
    if not m:
        raise HTTPException(404, "Match not found")
    await ensure_visible(db, user, m)
    return await build_live(db, m, user)
