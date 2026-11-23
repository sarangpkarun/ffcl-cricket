"""Roster changes: a captain asks to swap a player; an admin decides, and everything is re-checked then."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Match, MatchPlayer, RosterChange, Season, Team, TeamMember, User
from app.db.session import get_session
from app.deps import admin_scope, get_current_user, is_admin, season_admin
from app.routers.teams import can_manage
from app.services.approvals import ask_admins, tell
from app.services.archive import ensure_open
from app.services.outbox import flush as flush_outbox
from app.services.results import FINISHED
from app.services.schedule import team_people

router = APIRouter(tags=["roster"])


class RosterIn(BaseModel):
    out_user_id: int
    in_user_id: int
    reason: str = Field(min_length=3, max_length=500)


class DecisionIn(BaseModel):
    note: str = Field(min_length=3, max_length=500)


async def problems(db: AsyncSession, team: Team, out_id: int, in_id: int) -> list[str]:
    """Everything that stops this swap right now. Used when asking and again when approving."""
    out: list[str] = []
    if out_id == in_id:
        return ["Choose two different players"]
    member = await db.scalar(select(TeamMember).where(TeamMember.team_id == team.id, TeamMember.user_id == out_id,
                                                      TeamMember.status == "approved"))
    if member is None:
        out.append("The outgoing player is not an approved member of this team")
    if team.captain_id == out_id:
        out.append("The outgoing player is the captain; an admin must change the captain first")
    playing = list(await db.scalars(
        select(Match.match_no).join(MatchPlayer, MatchPlayer.match_id == Match.id)
        .where(MatchPlayer.user_id == out_id, Match.status.not_in(FINISHED)).order_by(Match.match_no)))
    if playing:
        out.append("The outgoing player is in the lineup of an unfinished match (match " + ", ".join(map(str, playing)) + ")")
    incoming = await db.get(User, in_id)
    if incoming is None:
        return [*out, "The incoming player does not exist"]
    if incoming.status != "active" or not incoming.phone_verified:
        out.append("The incoming player needs an active account and a verified phone")
    elsewhere = await db.scalar(
        select(TeamMember.id).join(Team, Team.id == TeamMember.team_id)
        .where(Team.season_id == team.season_id, TeamMember.user_id == in_id, TeamMember.status != "removed",
               ~((TeamMember.team_id == team.id) & (TeamMember.status == "pending"))))  # their own join request is fine
    if elsewhere:
        out.append("The incoming player is already in a team this season")
    return out


async def _out(db: AsyncSession, rows: list[RosterChange]) -> list[dict]:
    ids = {x for r in rows for x in (r.out_user_id, r.in_user_id, r.requested_by, r.decided_by) if x}
    users = {u.id: u for u in await db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}
    teams = {t.id: t for t in await db.scalars(select(Team).where(Team.id.in_({r.team_id for r in rows})))} if rows else {}

    def who(i: int | None) -> dict | None:
        u = users.get(i or 0)
        return {"id": u.id, "name": u.name, "player_code": u.player_code} if u else None

    return [{"id": r.id, "status": r.status, "reason": r.reason, "decision_note": r.decision_note,
             "team": {"id": r.team_id, "name": teams[r.team_id].name, "season_id": teams[r.team_id].season_id},
             "out": who(r.out_user_id), "in": who(r.in_user_id), "requested_by": who(r.requested_by),
             "decided_by": who(r.decided_by), "created_at": r.created_at.isoformat(),
             "decided_at": r.decided_at.isoformat() if r.decided_at else None} for r in rows]


@router.post("/teams/{team_id}/roster-changes", status_code=201)
async def request_change(team_id: int, body: RosterIn, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_session)) -> dict:
    team = await db.get(Team, team_id)
    if not team:
        raise HTTPException(404, "Team not found")
    await ensure_open(db, team.season_id)
    if not await can_manage(db, user, team):
        raise HTTPException(403, "Only the captain or an admin can ask for a roster change")
    found = await problems(db, team, body.out_user_id, body.in_user_id)
    if found:
        raise HTTPException(409, "; ".join(found))
    if await db.scalar(select(RosterChange.id).where(RosterChange.team_id == team_id, RosterChange.status == "pending",
                                                    or_(RosterChange.out_user_id == body.out_user_id,
                                                        RosterChange.in_user_id == body.in_user_id))):
        raise HTTPException(409, "There is already a pending request for one of these players")
    rc = RosterChange(team_id=team_id, out_user_id=body.out_user_id, in_user_id=body.in_user_id,
                      reason=body.reason.strip(), requested_by=user.id)
    db.add(rc)
    await db.flush()
    db.add(AuditLog(actor_id=user.id, action="roster.request", entity="roster_change", entity_id=rc.id, reason=rc.reason,
                    after={"team": team_id, "out": rc.out_user_id, "in": rc.in_user_id}))
    await ask_admins(db, "Roster change to approve", f"{team.name} asks to swap a player.", f"rc:{rc.id}", season_id=team.season_id)
    await db.commit()
    await flush_outbox(db)
    return (await _out(db, [rc]))[0]


@router.get("/roster-changes")
async def list_changes(status: str | None = Query(default=None, pattern="^(pending|approved|rejected|cancelled)$"),
                       team_id: int | None = None, season_id: int | None = None,
                       user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> list[dict]:
    q = select(RosterChange).order_by(RosterChange.id.desc()).limit(200)
    if status:
        q = q.where(RosterChange.status == status)
    if team_id:
        q = q.where(RosterChange.team_id == team_id)
    if season_id:
        q = q.where(RosterChange.team_id.in_(select(Team.id).where(Team.season_id == season_id)))
    scope = await admin_scope(db, user.id)
    if not scope.is_global:  # a season admin sees their seasons; captains see their own teams' requests; players see ones about them
        mine = [RosterChange.team_id.in_(select(Team.id).where(Team.captain_id == user.id)),
                RosterChange.out_user_id == user.id, RosterChange.in_user_id == user.id]
        if scope.seasons:
            mine.append(RosterChange.team_id.in_(select(Team.id).where(Team.season_id.in_(scope.seasons))))
        q = q.where(or_(*mine))
    return await _out(db, list(await db.scalars(q)))


async def _locked(db: AsyncSession, rc_id: int) -> RosterChange:
    rc = await db.scalar(select(RosterChange).where(RosterChange.id == rc_id).with_for_update())
    if not rc:
        raise HTTPException(404, "Request not found")
    if rc.status != "pending":
        raise HTTPException(409, f"This request was already {rc.status}")
    return rc


async def _finish(db: AsyncSession, rc: RosterChange, status: str, by: User, note: str | None) -> None:
    rc.status, rc.decided_by, rc.decided_at, rc.decision_note = status, by.id, datetime.now(UTC), note


@router.post("/roster-changes/{rc_id}/approve")
async def approve(rc_id: int, admin: User = Depends(season_admin("roster")), db: AsyncSession = Depends(get_session)) -> dict:
    rc = await _locked(db, rc_id)
    team = await db.get(Team, rc.team_id)
    assert team is not None
    await ensure_open(db, team.season_id)
    found = await problems(db, team, rc.out_user_id, rc.in_user_id)
    if found:
        raise HTTPException(409, "; ".join(found))
    out_m = await db.scalar(select(TeamMember).where(TeamMember.team_id == team.id, TeamMember.user_id == rc.out_user_id))
    assert out_m is not None
    out_m.status = "removed"
    if team.vice_captain_id == rc.out_user_id:
        team.vice_captain_id = None
    in_m = await db.scalar(select(TeamMember).where(TeamMember.team_id == team.id, TeamMember.user_id == rc.in_user_id))
    if in_m:
        in_m.status = "approved"
    else:
        db.add(TeamMember(team_id=team.id, user_id=rc.in_user_id, status="approved"))
    await _finish(db, rc, "approved", admin, None)
    db.add(AuditLog(actor_id=admin.id, action="roster.approve", entity="roster_change", entity_id=rc.id, reason=rc.reason,
                    before={"out": rc.out_user_id}, after={"in": rc.in_user_id, "team": team.id}))
    names = {u.id: u.name for u in await db.scalars(select(User).where(User.id.in_([rc.out_user_id, rc.in_user_id])))}
    await tell(db, await team_people(db, team.id) | {rc.out_user_id, rc.in_user_id, rc.requested_by}, "roster",
               "Roster change approved", f"{team.name}: {names[rc.in_user_id]} replaces {names[rc.out_user_id]}.",
               f"/teams/{team.id}", f"rc:{rc.id}:approved")
    await db.commit()
    await flush_outbox(db)
    return (await _out(db, [rc]))[0]


@router.post("/roster-changes/{rc_id}/reject")
async def reject(rc_id: int, body: DecisionIn, admin: User = Depends(season_admin("roster")),
                 db: AsyncSession = Depends(get_session)) -> dict:
    rc = await _locked(db, rc_id)
    await _finish(db, rc, "rejected", admin, body.note.strip())
    db.add(AuditLog(actor_id=admin.id, action="roster.reject", entity="roster_change", entity_id=rc.id, reason=body.note.strip()))
    team = await db.get(Team, rc.team_id)
    await tell(db, {rc.requested_by}, "roster", "Roster change rejected",
               f"{team.name if team else 'Your team'}: {body.note.strip()}", f"/teams/{rc.team_id}", f"rc:{rc.id}:rejected")
    await db.commit()
    await flush_outbox(db)
    return (await _out(db, [rc]))[0]


@router.post("/roster-changes/{rc_id}/cancel")
async def cancel(rc_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> dict:
    rc = await _locked(db, rc_id)
    team = await db.get(Team, rc.team_id)
    if rc.requested_by != user.id and not await is_admin(db, user, team.season_id if team else None):
        raise HTTPException(403, "Only the person who asked, or an admin, can cancel this")
    await _finish(db, rc, "cancelled", user, None)
    db.add(AuditLog(actor_id=user.id, action="roster.cancel", entity="roster_change", entity_id=rc.id))
    await db.commit()
    return (await _out(db, [rc]))[0]


@router.get("/seasons/{season_id}/roster-changes/summary")
async def summary(season_id: int, _: User = Depends(season_admin("season")), db: AsyncSession = Depends(get_session)) -> dict:
    if not await db.get(Season, season_id):
        raise HTTPException(404, "Season not found")
    n = len(list(await db.scalars(select(RosterChange.id).where(
        RosterChange.status == "pending", RosterChange.team_id.in_(select(Team.id).where(Team.season_id == season_id))))))
    return {"pending": n}
