from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Match, MatchPlayer, RuleSet, Season, Team, TeamMember, User
from app.db.session import get_session
from app.deps import get_current_user, is_admin, season_admin, user_roles
from app.engine.rules import DEFAULT_RULES
from app.realtime import publish_change
from app.routers.teams import can_manage
from app.schemas import LineupIn, MatchDetail, MatchIn, MatchOut, MatchPatch
from app.services import match_events
from app.services.announce import say, team_names
from app.services.archive import ensure_match_open, ensure_open
from app.services.chat import ensure_match_rooms
from app.services.duties import sync_duty
from app.services.notify import notify
from app.services.outbox import flush as flush_outbox
from app.services.schedule import ensure_visible, find_conflicts, team_people

router = APIRouter(tags=["matches"])


async def _match(db: AsyncSession, match_id: int) -> Match:
    m = await db.get(Match, match_id)
    if not m:
        raise HTTPException(404, "Match not found")
    return m


async def _check_umpire(db: AsyncSession, umpire_id: int | None, a: int, b: int) -> None:
    if umpire_id is None:
        return
    if "umpire" not in await user_roles(db, umpire_id):
        raise HTTPException(400, "Assigned user does not have the umpire role")
    playing = await db.scalar(
        select(TeamMember.id).where(
            TeamMember.user_id == umpire_id,
            TeamMember.team_id.in_([a, b]),
            TeamMember.status == "approved",
        )
    )
    if playing:
        raise HTTPException(400, "Umpire cannot belong to either team in this match")


@router.post("/seasons/{season_id}/matches", response_model=MatchOut, status_code=201)
async def create_match(
    season_id: int,
    body: MatchIn,
    admin: User = Depends(season_admin("season")),
    db: AsyncSession = Depends(get_session),
) -> Match:
    season = await db.get(Season, season_id)
    if not season:
        raise HTTPException(404, "Season not found")
    await ensure_open(db, season_id)
    if body.team_a_id == body.team_b_id:
        raise HTTPException(400, "A team cannot play itself")
    for tid in (body.team_a_id, body.team_b_id):
        team = await db.get(Team, tid)
        if not team or team.season_id != season_id:
            raise HTTPException(400, "Teams must belong to this season")
    await _check_umpire(db, body.umpire_id, body.team_a_id, body.team_b_id)
    clashes = await find_conflicts(db, season_id=season_id, team_ids=[body.team_a_id, body.team_b_id],
                                   umpire_id=body.umpire_id, when=body.scheduled_at)
    if clashes and not body.force:
        raise HTTPException(409, {"conflicts": clashes})
    rule_set_id = season.rule_set_id
    if rule_set_id is None:
        rs = RuleSet(name="FFCL", version=1, config=DEFAULT_RULES)
        db.add(rs)
        await db.flush()
        rule_set_id = rs.id
    max_no = await db.scalar(
        select(func.coalesce(func.max(Match.match_no), 0)).where(Match.season_id == season_id)
    )
    next_no = (max_no or 0) + 1
    # A match an admin creates by hand is visible at once; generated fixtures start as drafts.
    match = Match(season_id=season_id, match_no=next_no, rule_set_id=rule_set_id,
                  published_at=datetime.now(UTC), **body.model_dump(exclude={"force"}))
    db.add(match)
    await db.flush()
    if clashes:
        db.add(AuditLog(actor_id=admin.id, action="match.force_create", entity="match", entity_id=match.id,
                        reason="created despite clashes", after={"conflicts": clashes}))
    await ensure_match_rooms(db, match)
    await sync_duty(db, match)
    if match.umpire_id:
        await match_events.umpire_assigned(db, match, match.umpire_id)
    await db.commit()
    await flush_outbox(db)
    return match


@router.get("/seasons/{season_id}/matches", response_model=list[MatchOut])
async def list_matches(
    season_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)
) -> list[Match]:
    q = select(Match).where(Match.season_id == season_id).order_by(Match.match_no)
    if not await is_admin(db, user, season_id):
        q = q.where(Match.published_at.is_not(None))  # drafts are admin-only
    return list(await db.scalars(q))


@router.get("/matches/{match_id}", response_model=MatchDetail)
async def get_match(
    match_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)
) -> MatchDetail:
    m = await _match(db, match_id)
    await ensure_visible(db, user, m)
    lineup = list(
        await db.scalars(
            select(MatchPlayer).where(MatchPlayer.match_id == match_id).order_by(MatchPlayer.id)
        )
    )
    return MatchDetail(**MatchOut.model_validate(m).model_dump(), lineup=lineup)  # type: ignore[arg-type]


@router.patch("/matches/{match_id}", response_model=MatchOut)
async def update_match(
    match_id: int,
    body: MatchPatch,
    admin: User = Depends(season_admin("match")),
    db: AsyncSession = Depends(get_session),
) -> Match:
    m = await _match(db, match_id)
    await ensure_match_open(db, m)
    if m.status != "scheduled":
        raise HTTPException(409, "Only scheduled matches can be edited")
    data = body.model_dump(exclude_unset=True)
    force = data.pop("force", False)
    if "umpire_id" in data:
        await _check_umpire(db, data["umpire_id"], m.team_a_id, m.team_b_id)
    new_when = data.get("scheduled_at", m.scheduled_at)
    new_umpire = data.get("umpire_id", m.umpire_id)
    clashes: list[str] = []
    if "scheduled_at" in data or "umpire_id" in data:
        clashes = await find_conflicts(db, season_id=m.season_id, team_ids=[m.team_a_id, m.team_b_id],
                                       umpire_id=new_umpire, when=new_when, exclude_match_id=m.id)
        if clashes and not force:
            raise HTTPException(409, {"conflicts": clashes})
    previous_umpire, old_when = m.umpire_id, m.scheduled_at
    for k, v in data.items():
        setattr(m, k, v)
    m.seq += 1
    if "umpire_id" in data:
        await sync_duty(db, m)
    if clashes:
        db.add(AuditLog(actor_id=admin.id, action="match.force_update", entity="match", entity_id=m.id,
                        reason="saved despite clashes", after={"conflicts": clashes}))
    if m.published_at is not None:
        if data.get("umpire_id") and data["umpire_id"] != previous_umpire:
            await match_events.umpire_assigned(db, m, data["umpire_id"])
        if "scheduled_at" in data and data["scheduled_at"] != old_when:
            names = await team_names(db, m)
            versus = f"{names[m.team_a_id]} vs {names[m.team_b_id]}"
            when = new_when.astimezone(UTC).strftime("%a %d %b %H:%M UTC") if new_when else "a time to be confirmed"
            was = old_when.astimezone(UTC).strftime("%a %d %b %H:%M UTC") if old_when else "unscheduled"
            await say(db, m, f"📅 Match moved to {when} (was {was}).")
            people = await team_people(db, m.team_a_id) | await team_people(db, m.team_b_id) | ({m.umpire_id} if m.umpire_id else set())
            await notify(db, people, "fixture_change", f"Match {m.match_no} rescheduled", f"{versus}: now {when}.",
                         {"link": f"/matches/{m.id}", "match_id": m.id}, f"resched:{m.id}:{new_when.isoformat() if new_when else 'none'}")
    await db.commit()
    await publish_change(m.id, m.seq)
    await flush_outbox(db)
    return m


@router.put("/matches/{match_id}/lineup", response_model=MatchDetail)
async def set_lineup(
    match_id: int,
    body: LineupIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> MatchDetail:
    m = await _match(db, match_id)
    await ensure_visible(db, user, m)
    await ensure_match_open(db, m)
    if body.team_id not in (m.team_a_id, m.team_b_id):
        raise HTTPException(400, "Team is not part of this match")
    if m.status not in ("scheduled", "toss"):
        raise HTTPException(409, "Lineup is locked once the match is ready")
    team = await db.get(Team, body.team_id)
    assert team is not None
    if not await can_manage(db, user, team):
        raise HTTPException(403, "Only the captain or an admin can set the lineup")
    ids = body.user_ids
    limit = int(DEFAULT_RULES["players_per_team"])  # type: ignore[call-overload]
    if len(set(ids)) != len(ids):
        raise HTTPException(400, "Duplicate players in lineup")
    if not ids or len(ids) > limit:
        raise HTTPException(400, f"Lineup needs 1 to {limit} players")
    approved = set(
        await db.scalars(
            select(TeamMember.user_id).where(
                TeamMember.team_id == body.team_id, TeamMember.status == "approved"
            )
        )
    )
    if not set(ids) <= approved:
        raise HTTPException(400, "All players must be approved team members")
    users = list(await db.scalars(select(User).where(User.id.in_(ids))))
    bad = [u.name for u in users if u.status != "active" or not u.phone_verified]
    if bad:
        raise HTTPException(
            400, f"Players need an active account and verified phone: {', '.join(bad)}"
        )
    await db.execute(
        delete(MatchPlayer).where(MatchPlayer.match_id == match_id, MatchPlayer.team_id == body.team_id)
    )
    for order, uid in enumerate(ids, start=1):
        db.add(MatchPlayer(match_id=match_id, team_id=body.team_id, user_id=uid, batting_order=order))
    m.seq += 1
    await db.commit()
    await publish_change(m.id, m.seq)
    return await get_match(match_id, user, db)
