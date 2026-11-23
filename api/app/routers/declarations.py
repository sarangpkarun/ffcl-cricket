"""Walkovers, abandonments and their reversal."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.session import get_session
from app.deps import get_current_user, is_admin
from app.routers.play import commit_match, ensure_official, lock_match
from app.services import declarations as svc

router = APIRouter(tags=["declarations"])
Reason = Field(min_length=3, max_length=500)


class WalkoverIn(BaseModel):
    absent_team_id: int
    reason: str = Reason


class AbandonIn(BaseModel):
    reason: str = Reason
    replay: bool = False  # create a draft replay match
    replay_at: datetime | None = None


class ReverseIn(BaseModel):
    reason: str = Reason


@router.post("/matches/{match_id}/walkover")
async def walkover(match_id: int, body: WalkoverIn, user: User = Depends(get_current_user),
                   db: AsyncSession = Depends(get_session)) -> dict:
    """One team did not turn up: the other is awarded the win. Only before the match starts."""
    m = await lock_match(db, match_id)
    await ensure_official(db, user, m)
    await svc.declare_walkover(db, m, body.absent_team_id, body.reason.strip(), user)
    await commit_match(db, m)
    return {"status": m.status, "winner_team_id": m.winner_team_id, "result": m.result_text}


@router.post("/matches/{match_id}/abandon")
async def abandon(match_id: int, body: AbandonIn, user: User = Depends(get_current_user),
                  db: AsyncSession = Depends(get_session)) -> dict:
    """Stop a match for good (weather, a dispute, too few players). Whatever was played is kept."""
    m = await lock_match(db, match_id)
    await ensure_official(db, user, m)
    decl = await svc.declare_abandon(db, m, body.reason.strip(), user, body.replay, body.replay_at)
    await commit_match(db, m)
    return {"status": m.status, "result": m.result_text, "replay_match_id": decl.replay_match_id}


@router.post("/matches/{match_id}/result/reverse")
async def reverse(match_id: int, body: ReverseIn, user: User = Depends(get_current_user),
                  db: AsyncSession = Depends(get_session)) -> dict:
    """Undo a walkover or abandonment (admins only). The match returns to what it was before."""
    m = await lock_match(db, match_id)
    if not await is_admin(db, user, m.season_id):
        raise HTTPException(403, "Only an admin can reverse a walkover or abandonment")
    await svc.reverse_declaration(db, m, body.reason.strip(), user)
    await commit_match(db, m)
    return {"status": m.status, "paused": m.paused}
