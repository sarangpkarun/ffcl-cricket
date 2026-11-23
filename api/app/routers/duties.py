"""Umpire duty records."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Match, Team, UmpireDuty, User
from app.db.session import get_session
from app.deps import get_current_user, is_admin, season_admin
from app.services import duties as svc
from app.services.archive import ensure_match_open
from app.services.outbox import flush as flush_outbox

router = APIRouter(tags=["duties"])


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


async def _rows(db: AsyncSession, duties: list[UmpireDuty]) -> list[dict]:
    if not duties:
        return []
    matches = {m.id: m for m in await db.scalars(select(Match).where(Match.id.in_({d.match_id for d in duties})))}
    team_ids = {t for m in matches.values() for t in (m.team_a_id, m.team_b_id)} | {d.team_id for d in duties if d.team_id}
    teams = {t.id: t.name for t in await db.scalars(select(Team).where(Team.id.in_(team_ids)))}
    users = {u.id: u.name for u in await db.scalars(select(User).where(User.id.in_({d.umpire_id for d in duties})))}
    out = []
    for d in duties:
        m = matches[d.match_id]
        out.append({
            "id": d.id, "status": d.status, "note": d.note, "adjustment_id": d.adjustment_id,
            "umpire": {"id": d.umpire_id, "name": users.get(d.umpire_id)},
            "team": {"id": d.team_id, "name": teams.get(d.team_id)} if d.team_id else None,
            "match": {"id": m.id, "match_no": m.match_no, "status": m.status,
                      "scheduled_at": m.scheduled_at.isoformat() if m.scheduled_at else None,
                      "teams": f"{teams.get(m.team_a_id)} vs {teams.get(m.team_b_id)}"},
        })
    return out


@router.get("/seasons/{season_id}/duties")
async def season_duties(season_id: int, status: str | None = Query(default=None, pattern="^(assigned|performed|missed|replaced)$"),
                        _: User = Depends(season_admin("season")), db: AsyncSession = Depends(get_session)) -> list[dict]:
    q = select(UmpireDuty).join(Match, Match.id == UmpireDuty.match_id).where(Match.season_id == season_id)
    if status:
        q = q.where(UmpireDuty.status == status)
    return await _rows(db, list(await db.scalars(q.order_by(Match.scheduled_at.nulls_last(), UmpireDuty.id))))


@router.get("/me/duties")
async def my_duties(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> list[dict]:
    q = select(UmpireDuty).where(UmpireDuty.umpire_id == user.id, UmpireDuty.status != "replaced").order_by(UmpireDuty.id.desc())
    return await _rows(db, list(await db.scalars(q)))


@router.post("/duties/{duty_id}/missed")
async def duty_missed(duty_id: int, body: ReasonIn, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_session)) -> dict:
    """Record that the assigned umpire did not turn up. An admin, or the umpire who stepped in, can do this."""
    duty = await svc.get_duty(db, duty_id)
    match = await db.get(Match, duty.match_id)
    assert match is not None
    await ensure_match_open(db, match)
    stepped_in = match.umpire_id == user.id and user.id != duty.umpire_id
    if not (await is_admin(db, user, match.season_id) or stepped_in):
        raise HTTPException(403, "Only an admin, or the umpire who took over, can record a missed duty")
    adj = await svc.mark_missed(db, duty, user, body.reason.strip())
    await db.commit()
    await flush_outbox(db)
    return {"status": duty.status, "points_deducted": -adj.points if adj else 0}


@router.post("/duties/{duty_id}/reverse")
async def duty_reverse(duty_id: int, body: ReasonIn, admin: User = Depends(season_admin("duty")),
                       db: AsyncSession = Depends(get_session)) -> dict:
    duty = await svc.get_duty(db, duty_id)
    await ensure_match_open(db, await db.get(Match, duty.match_id))  # type: ignore[arg-type]
    await svc.reverse_missed(db, duty, admin, body.reason.strip())
    await db.commit()
    await flush_outbox(db)
    return {"status": duty.status}
