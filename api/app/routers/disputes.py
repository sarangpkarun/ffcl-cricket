"""Disputes and complaints. Never public: see services/disputes.py for who can see and decide what."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Dispute, DisputeMessage, Match, Season, Team, User
from app.db.session import get_session
from app.deps import any_admin, get_current_user, is_admin, season_admin
from app.routers.auth import throttle
from app.services import disputes as svc
from app.services.outbox import flush as flush_outbox

router = APIRouter(tags=["disputes"])
Body = Field(min_length=10, max_length=2000)


class RaiseIn(BaseModel):
    kind: str
    body: str = Body
    match_id: int | None = None
    season_id: int | None = None
    against_team_id: int | None = None


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    internal: bool = False


class DecideIn(BaseModel):
    outcome: str = Field(min_length=10, max_length=2000)
    action: str = "none"
    adjustment_id: int | None = None


class ReopenIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


async def _get(db: AsyncSession, dispute_id: int, user: User) -> tuple[Dispute, str]:
    d = await db.get(Dispute, dispute_id)
    lvl = await svc.level(db, user, d) if d else None
    if d is None or lvl is None:
        raise HTTPException(404, "Dispute not found")  # the same answer whether it exists or not
    return d, lvl


async def _summary(db: AsyncSession, rows: list[Dispute]) -> list[dict]:
    mids = {d.match_id for d in rows if d.match_id}
    matches = {m.id: m for m in await db.scalars(select(Match).where(Match.id.in_(mids)))} if mids else {}
    tids = {t for m in matches.values() for t in (m.team_a_id, m.team_b_id)} | {d.against_team_id for d in rows if d.against_team_id}
    teams = {t.id: t.name for t in await db.scalars(select(Team).where(Team.id.in_(tids)))} if tids else {}
    uids = {d.raised_by for d in rows} | {d.assigned_to for d in rows if d.assigned_to}
    users = {u.id: u for u in await db.scalars(select(User).where(User.id.in_(uids)))} if uids else {}
    seasons = {s.id: s.name for s in await db.scalars(select(Season).where(Season.id.in_({d.season_id for d in rows})))} if rows else {}
    out = []
    for d in rows:
        m = matches.get(d.match_id or 0)
        out.append({
            "id": d.id, "kind": d.kind, "status": d.status, "season": {"id": d.season_id, "name": seasons.get(d.season_id)},
            "match": {"id": m.id, "match_no": m.match_no, "teams": f"{teams.get(m.team_a_id)} vs {teams.get(m.team_b_id)}"} if m else None,
            "against": teams.get(d.against_team_id or 0), "raised_by": {"id": d.raised_by, "name": users[d.raised_by].name, "as": d.raised_as},
            "assigned_to": users[d.assigned_to].name if d.assigned_to in users else None, "excerpt": d.body[:140],
            "created_at": d.created_at.isoformat(), "updated_at": d.updated_at.isoformat(),
        })
    return out


@router.post("/disputes", status_code=201)
async def raise_one(body: RaiseIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> dict:
    await throttle("dispute-raise", str(user.id), 5, 3600)
    d = await svc.raise_dispute(db, user, kind=body.kind, body=body.body, match_id=body.match_id, season_id=body.season_id,
                                against_team_id=body.against_team_id)
    await db.commit()
    await flush_outbox(db)
    return {"id": d.id, "status": d.status}


@router.get("/disputes")
async def mine(status: str = Query(default="all", pattern="^(all|open|closed)$"), user: User = Depends(get_current_user),
               db: AsyncSession = Depends(get_session)) -> list[dict]:
    """Disputes I raised, or that involve a team I captain."""
    led = set(await db.scalars(select(Team.id).where((Team.captain_id == user.id) | (Team.vice_captain_id == user.id))))
    cond = [Dispute.raised_by == user.id]
    if led:
        in_matches = select(Match.id).where(or_(Match.team_a_id.in_(led), Match.team_b_id.in_(led)))
        cond += [Dispute.against_team_id.in_(led), Dispute.match_id.in_(in_matches)]
    q = select(Dispute).where(or_(*cond)).order_by(Dispute.updated_at.desc()).limit(200)
    if status == "open":
        q = q.where(Dispute.status.in_(svc.OPEN))
    elif status == "closed":
        q = q.where(Dispute.status.in_(svc.CLOSED))
    rows = [d for d in await db.scalars(q) if await svc.level(db, user, d)]
    return await _summary(db, rows)


@router.get("/matches/{match_id}/disputes")
async def for_match(match_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> dict:
    """What I may do about this match, and the disputes about it that I am allowed to see."""
    m = await db.get(Match, match_id)
    if not m or (m.published_at is None and not await is_admin(db, user, m.season_id)):
        raise HTTPException(404, "Match not found")
    rows = [d for d in await db.scalars(select(Dispute).where(Dispute.match_id == match_id).order_by(Dispute.id))
            if await svc.level(db, user, d)]
    return {**await svc.can_raise(db, user, m), "disputes": await _summary(db, rows)}


@router.get("/disputes/{dispute_id}")
async def detail(dispute_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> dict:
    d, lvl = await _get(db, dispute_id, user)
    msgs = list(await db.scalars(select(DisputeMessage).where(DisputeMessage.dispute_id == d.id).order_by(DisputeMessage.id)))
    if lvl != "admin":
        msgs = [x for x in msgs if not x.internal]  # private notes are for the judges only
    authors = {u.id: u for u in await db.scalars(select(User).where(User.id.in_({x.author_id for x in msgs} | {d.raised_by})))}
    resolver = await db.get(User, d.resolved_by) if d.resolved_by else None
    base = (await _summary(db, [d]))[0]
    m = await db.get(Match, d.match_id) if d.match_id else None
    open_ = d.status in svc.OPEN
    return {
        **base, "body": d.body, "outcome": d.outcome, "resolution": d.resolution_ref,
        "resolved_by": resolver.name if resolver else None, "resolved_at": d.resolved_at.isoformat() if d.resolved_at else None,
        "match_status": m.status if m else None, "match_result": m.result_text if m else None,
        "messages": [{"id": x.id, "author": {"id": x.author_id, "name": authors[x.author_id].name,
                                              "is_raiser": x.author_id == d.raised_by}, "body": x.body, "internal": x.internal,
                      "created_at": x.created_at.isoformat()} for x in msgs],
        "viewer": {"level": lvl, "can_message": open_ or lvl == "admin", "can_take": lvl == "admin" and open_ and d.assigned_to != user.id,
                   "can_decide": lvl == "admin" and open_, "can_reopen": lvl == "admin" and not open_,
                   "can_withdraw": user.id == d.raised_by and open_},
    }


@router.post("/disputes/{dispute_id}/messages", status_code=201)
async def post_message(dispute_id: int, body: MessageIn, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_session)) -> dict:
    await throttle("dispute-message", str(user.id), 40, 3600)
    d, _ = await _get(db, dispute_id, user)
    msg = await svc.add_message(db, user, d, body.body, body.internal)
    await db.commit()
    await flush_outbox(db)
    return {"id": msg.id}


@router.post("/disputes/{dispute_id}/withdraw", status_code=204)
async def withdraw(dispute_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> None:
    d, _ = await _get(db, dispute_id, user)
    await svc.withdraw(db, user, d)
    await db.commit()
    await flush_outbox(db)


# ---------- admins ----------
@router.get("/admin/disputes")
async def queue(status: str = Query(default="open", pattern="^(all|open|closed)$"), kind: str | None = None,
                season_id: int | None = None, assigned: str | None = Query(default=None, pattern="^(me|nobody)$"),
                admin: User = Depends(any_admin), db: AsyncSession = Depends(get_session)) -> list[dict]:
    """Every dispute I may decide (ones I am involved in are not shown here)."""
    q = select(Dispute).order_by(Dispute.created_at).limit(300)
    if status == "open":
        q = q.where(Dispute.status.in_(svc.OPEN))
    elif status == "closed":
        q = q.where(Dispute.status.in_(svc.CLOSED)).order_by(None).order_by(Dispute.updated_at.desc())
    if kind:
        q = q.where(Dispute.kind == kind)
    if season_id:
        q = q.where(Dispute.season_id == season_id)
    if assigned == "me":
        q = q.where(Dispute.assigned_to == admin.id)
    elif assigned == "nobody":
        q = q.where(Dispute.assigned_to.is_(None))
    rows = [d for d in await db.scalars(q) if await svc.level(db, admin, d) == "admin"]
    return await _summary(db, rows)


@router.get("/admin/disputes/summary")
async def summary(admin: User = Depends(any_admin), db: AsyncSession = Depends(get_session)) -> dict:
    now = datetime.now(UTC)
    rows = [d for d in await db.scalars(select(Dispute).where(Dispute.status.in_(svc.OPEN)).limit(500))
            if await svc.level(db, admin, d) == "admin"]
    return {"open": sum(d.status == "open" for d in rows), "in_review": sum(d.status == "in_review" for d in rows),
            "stale": sum(now - d.created_at > svc.STALE_AFTER for d in rows),
            "mine": sum(d.assigned_to == admin.id for d in rows)}


@router.post("/admin/disputes/{dispute_id}/take", status_code=204)
async def take(dispute_id: int, admin: User = Depends(season_admin("dispute")), db: AsyncSession = Depends(get_session)) -> None:
    d, _ = await _get(db, dispute_id, admin)
    await svc.take(db, admin, d)
    await db.commit()
    await flush_outbox(db)


@router.post("/admin/disputes/{dispute_id}/resolve", status_code=204)
async def resolve(dispute_id: int, body: DecideIn, admin: User = Depends(season_admin("dispute")), db: AsyncSession = Depends(get_session)) -> None:
    d, _ = await _get(db, dispute_id, admin)
    await svc.decide(db, admin, d, status="resolved", outcome=body.outcome, action=body.action, adjustment_id=body.adjustment_id)
    await db.commit()
    await flush_outbox(db)


@router.post("/admin/disputes/{dispute_id}/dismiss", status_code=204)
async def dismiss(dispute_id: int, body: DecideIn, admin: User = Depends(season_admin("dispute")), db: AsyncSession = Depends(get_session)) -> None:
    d, _ = await _get(db, dispute_id, admin)
    await svc.decide(db, admin, d, status="dismissed", outcome=body.outcome, action="none")
    await db.commit()
    await flush_outbox(db)


@router.post("/admin/disputes/{dispute_id}/reopen", status_code=204)
async def reopen(dispute_id: int, body: ReopenIn, admin: User = Depends(season_admin("dispute")), db: AsyncSession = Depends(get_session)) -> None:
    d, _ = await _get(db, dispute_id, admin)
    await svc.reopen(db, admin, d, body.reason)
    await db.commit()
    await flush_outbox(db)
