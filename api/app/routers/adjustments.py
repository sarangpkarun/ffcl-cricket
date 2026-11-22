"""Manual points adjustments (conduct, corrections). Umpire-duty penalties are created by the duty flow."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Match, PointAdjustment, Season, Team, User
from app.db.session import get_session
from app.deps import require_admin
from app.services.archive import ensure_open
from app.services.notify import notify
from app.services.outbox import flush as flush_outbox
from app.services.schedule import team_people

router = APIRouter(tags=["adjustments"])


class AdjustmentIn(BaseModel):
    team_id: int
    points: int = Field(ge=-50, le=50)
    kind: str = Field(default="manual", pattern="^(manual|conduct)$")
    reason: str = Field(min_length=3, max_length=500)
    match_id: int | None = None

    @field_validator("points")
    @classmethod
    def _nonzero(cls, v: int) -> int:
        if v == 0:
            raise ValueError("An adjustment of zero points does nothing")
        return v


class VoidIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


def _out(a: PointAdjustment, team: str | None, who: str | None) -> dict:
    return {"id": a.id, "team": {"id": a.team_id, "name": team}, "points": a.points, "kind": a.kind, "reason": a.reason,
            "match_id": a.match_id, "created_by": who, "created_at": a.created_at.isoformat(),
            "voided": a.voided_at is not None, "voided_at": a.voided_at.isoformat() if a.voided_at else None}


@router.get("/seasons/{season_id}/adjustments")
async def list_adjustments(season_id: int, include_voided: bool = False, _: User = Depends(require_admin),
                           db: AsyncSession = Depends(get_session)) -> list[dict]:
    if not await db.get(Season, season_id):
        raise HTTPException(404, "Season not found")
    q = select(PointAdjustment).where(PointAdjustment.season_id == season_id).order_by(PointAdjustment.id.desc())
    if not include_voided:
        q = q.where(PointAdjustment.voided_at.is_(None))
    rows = list(await db.scalars(q))
    teams = {t.id: t.name for t in await db.scalars(select(Team).where(Team.season_id == season_id))}
    users = {u.id: u.name for u in await db.scalars(select(User).where(User.id.in_({a.created_by for a in rows})))} if rows else {}
    return [_out(a, teams.get(a.team_id), users.get(a.created_by)) for a in rows]


@router.post("/seasons/{season_id}/adjustments", status_code=201)
async def add_adjustment(season_id: int, body: AdjustmentIn, admin: User = Depends(require_admin),
                         db: AsyncSession = Depends(get_session)) -> dict:
    if not await db.get(Season, season_id):
        raise HTTPException(404, "Season not found")
    await ensure_open(db, season_id)
    team = await db.get(Team, body.team_id)
    if not team or team.season_id != season_id:
        raise HTTPException(422, "The team must belong to this season")
    if body.match_id is not None:
        m = await db.get(Match, body.match_id)
        if not m or m.season_id != season_id:
            raise HTTPException(422, "The match must belong to this season")
    adj = PointAdjustment(season_id=season_id, team_id=body.team_id, match_id=body.match_id, points=body.points,
                          kind=body.kind, reason=body.reason.strip(), created_by=admin.id)
    db.add(adj)
    await db.flush()
    db.add(AuditLog(actor_id=admin.id, action="adjustment.add", entity="point_adjustment", entity_id=adj.id,
                    reason=adj.reason, after={"team": body.team_id, "points": body.points, "kind": body.kind}))
    sign = "+" if body.points > 0 else ""
    await notify(db, await team_people(db, body.team_id), "adjustment", "Points adjustment",
                 f"{team.name}: {sign}{body.points} point{'' if abs(body.points) == 1 else 's'}. {adj.reason}",
                 {"link": "/standings"}, f"adj:{adj.id}")
    await db.commit()
    await flush_outbox(db)
    return _out(adj, team.name, admin.name)


@router.post("/adjustments/{adjustment_id}/void")
async def void_adjustment(adjustment_id: int, body: VoidIn, admin: User = Depends(require_admin),
                          db: AsyncSession = Depends(get_session)) -> dict:
    adj = await db.get(PointAdjustment, adjustment_id)
    if adj is None:
        raise HTTPException(404, "Adjustment not found")
    await ensure_open(db, adj.season_id)
    if adj.voided_at is None:
        adj.voided_at = datetime.now(UTC)
        db.add(AuditLog(actor_id=admin.id, action="adjustment.void", entity="point_adjustment", entity_id=adj.id,
                        reason=body.reason.strip()))
        team = await db.get(Team, adj.team_id)
        await notify(db, await team_people(db, adj.team_id), "adjustment", "Points adjustment cancelled",
                     f"{team.name if team else 'Your team'}: an adjustment of {adj.points:+d} was cancelled.",
                     {"link": "/standings"}, f"adj:{adj.id}:void")
        await db.commit()
        await flush_outbox(db)
    team = await db.get(Team, adj.team_id)
    return _out(adj, team.name if team else None, admin.name)
