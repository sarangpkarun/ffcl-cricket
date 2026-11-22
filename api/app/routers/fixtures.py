"""Fixtures: generate a season's schedule as drafts, review it, then publish it."""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Match, RuleSet, Season, Stage, Team, User
from app.db.session import get_session
from app.deps import get_current_user, is_admin, require_admin
from app.engine.fixtures import PlannedMatch, round_robin, schedule, slot_times, umpire_plan
from app.engine.rules import DEFAULT_RULES
from app.realtime import publish_change
from app.services import match_events
from app.services.chat import ensure_match_rooms
from app.services.duties import sync_duty
from app.services.notify import notify
from app.services.outbox import flush as flush_outbox
from app.services.schedule import (
    delete_draft_match,
    find_conflicts,
    team_members,
    team_people,
    umpire_candidates,
)

router = APIRouter(tags=["fixtures"])
LIVE = ("innings1", "break", "innings2")
UPCOMING = ("scheduled", "toss", "ready")
DONE = ("completed", "abandoned")


class FixtureParams(BaseModel):
    stage_name: str = Field(default="League", min_length=1, max_length=60)
    legs: int = Field(default=1, ge=1, le=2)  # 1 = everyone plays everyone once, 2 = home and away
    start_date: date
    times: list[time] = Field(min_length=1, max_length=12)  # local kick-off times
    weekdays: list[int] | None = None  # 0 = Monday ... 6 = Sunday; none = every day
    parallel: int = Field(default=2, ge=1, le=8)  # matches that can run at the same time
    rest_slots: int = Field(default=1, ge=0, le=5)  # slots a team sits out between its matches
    assign_umpires: bool = True
    team_ids: list[int] | None = None  # default: every team in the season
    timezone: str = "UTC"  # the league's local time zone, e.g. "Asia/Kolkata"

    @field_validator("weekdays")
    @classmethod
    def _days(cls, v: list[int] | None) -> list[int] | None:
        if v is not None and (not v or any(d < 0 or d > 6 for d in v)):
            raise ValueError("weekdays must be numbers from 0 (Monday) to 6 (Sunday)")
        return v


class GenerateParams(FixtureParams):
    replace_drafts: bool = False  # throw away the unpublished league stage and build a new one


def _audit(db: AsyncSession, actor: User, action: str, entity: str, entity_id: int | None,
           reason: str | None = None, after: dict | None = None) -> None:
    db.add(AuditLog(actor_id=actor.id, action=action, entity=entity, entity_id=entity_id, reason=reason, after=after))


def _when(dt: datetime | None) -> str:
    return dt.astimezone(UTC).strftime("%a %d %b %H:%M UTC") if dt else "time to be confirmed"


async def _season(db: AsyncSession, season_id: int) -> Season:
    season = await db.get(Season, season_id)
    if not season:
        raise HTTPException(404, "Season not found")
    return season


async def _plan(db: AsyncSession, season: Season, p: FixtureParams) -> dict:
    """Work out the whole schedule without saving anything."""
    teams = {t.id: t for t in await db.scalars(select(Team).where(Team.season_id == season.id).order_by(Team.id))}
    ids = p.team_ids if p.team_ids is not None else list(teams)
    if any(i not in teams for i in ids):
        raise HTTPException(422, "Every team must belong to this season")
    try:
        pairings = round_robin(ids, p.legs)
        tz = ZoneInfo(p.timezone)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except ZoneInfoNotFoundError as e:
        raise HTTPException(422, f"Unknown time zone {p.timezone!r}") from e
    rounds = max(x.round_no for x in pairings)
    needed = len(pairings) * (p.rest_slots + 1) + rounds + 5
    slots = [dt.replace(tzinfo=tz).astimezone(UTC) for dt in slot_times(p.start_date, p.times, p.weekdays, needed)]
    placed = schedule(pairings, slots, parallel=p.parallel, rest_slots=p.rest_slots)
    members = await team_members(db, ids)
    plan: dict[int, int | None] = dict.fromkeys(range(len(placed)))
    candidates = await umpire_candidates(db, season.id) if p.assign_umpires else {}
    if p.assign_umpires:
        plan = umpire_plan(placed, candidates, members)
    names: dict[int, str] = {u.id: u.name for u in await db.scalars(select(User).where(User.id.in_({u for u in plan.values() if u})))} if any(plan.values()) else {}
    rows = []
    for idx, m in enumerate(placed):
        a, b = m.pairing.home, m.pairing.away
        warnings = await find_conflicts(db, season_id=season.id, team_ids=[a, b], umpire_id=plan[idx], when=m.when)
        if p.assign_umpires and plan[idx] is None:
            warnings.append("No umpire available: assign one before publishing")
        rows.append({"index": idx, "round_no": m.pairing.round_no, "round_label": f"Round {m.pairing.round_no}",
                     "team_a_id": a, "team_b_id": b, "team_a": teams[a].name, "team_b": teams[b].name,
                     "scheduled_at": m.when.isoformat(), "umpire_id": plan[idx], "umpire": names.get(plan[idx] or 0),
                     "warnings": warnings})
    home = {t: sum(1 for x in placed if x.pairing.home == t) for t in ids}
    away = {t: sum(1 for x in placed if x.pairing.away == t) for t in ids}
    return {
        "matches": rows,
        "summary": {
            "teams": len(ids), "matches": len(rows), "rounds": rounds, "legs": p.legs,
            "first": rows[0]["scheduled_at"], "last": rows[-1]["scheduled_at"],
            "without_umpire": sum(1 for r in rows if r["umpire_id"] is None) if p.assign_umpires else None,
            "with_warnings": sum(1 for r in rows if r["warnings"]),
            "home_away": {teams[t].name: {"home": home[t], "away": away[t]} for t in ids},
        },
        "_placed": placed,
    }


@router.post("/seasons/{season_id}/fixtures/preview")
async def preview(season_id: int, body: FixtureParams, _: User = Depends(require_admin),
                  db: AsyncSession = Depends(get_session)) -> dict:
    """Show what would be generated. Nothing is saved."""
    plan = await _plan(db, await _season(db, season_id), body)
    plan.pop("_placed")
    return plan


@router.post("/seasons/{season_id}/fixtures/generate", status_code=201)
async def generate(season_id: int, body: GenerateParams, admin: User = Depends(require_admin),
                   db: AsyncSession = Depends(get_session)) -> dict:
    """Create the league stage and its matches as unpublished drafts."""
    season = await _season(db, season_id)
    existing = list(await db.scalars(select(Stage).where(Stage.season_id == season_id, Stage.kind == "round_robin")))
    if existing and not body.replace_drafts:
        raise HTTPException(409, "This season already has a league stage. Use replace_drafts to rebuild its drafts.")
    for st in existing:
        matches = list(await db.scalars(select(Match).where(Match.stage_id == st.id)))
        if any(m.published_at is not None or m.status != "scheduled" for m in matches):
            raise HTTPException(409, "The league stage already has published matches; they cannot be replaced")
        for m in matches:
            await delete_draft_match(db, m)
        await db.delete(st)
    await db.flush()

    plan = await _plan(db, season, body)
    placed: list[PlannedMatch] = plan.pop("_placed")
    rule_set_id = season.rule_set_id
    if rule_set_id is None:
        rs = RuleSet(name="FFCL", version=1, config=DEFAULT_RULES)
        db.add(rs)
        await db.flush()
        rule_set_id = rs.id
    next_ord = (await db.scalar(select(func.coalesce(func.max(Stage.ord), 0)).where(Stage.season_id == season_id)) or 0) + 1
    stage = Stage(season_id=season_id, kind="round_robin", name=body.stage_name, ord=next_ord,
                  config={"legs": body.legs, "parallel": body.parallel, "rest_slots": body.rest_slots})
    db.add(stage)
    await db.flush()
    number = (await db.scalar(select(func.coalesce(func.max(Match.match_no), 0)).where(Match.season_id == season_id)) or 0)
    created = []
    for row, pm in zip(plan["matches"], placed, strict=True):
        number += 1
        match = Match(season_id=season_id, match_no=number, team_a_id=row["team_a_id"], team_b_id=row["team_b_id"],
                      umpire_id=row["umpire_id"], rule_set_id=rule_set_id, scheduled_at=pm.when,
                      stage_id=stage.id, round_label=row["round_label"], published_at=None)
        db.add(match)
        await db.flush()
        await ensure_match_rooms(db, match)
        await sync_duty(db, match)
        created.append(match.id)
    _audit(db, admin, "fixtures.generate", "season", season_id,
           after={"stage": stage.id, "matches": len(created), "legs": body.legs})
    await db.commit()
    return {"stage_id": stage.id, "created": len(created), "match_ids": created, "summary": plan["summary"]}


class PublishIn(BaseModel):
    match_ids: list[int] | None = None  # default: every draft in the season
    stage_id: int | None = None


@router.post("/seasons/{season_id}/fixtures/publish")
async def publish(season_id: int, body: PublishIn, admin: User = Depends(require_admin),
                  db: AsyncSession = Depends(get_session)) -> dict:
    """Make drafts visible and tell everybody involved. Safe to repeat: published matches are skipped."""
    await _season(db, season_id)
    q = select(Match).where(Match.season_id == season_id, Match.published_at.is_(None)).order_by(Match.scheduled_at, Match.id)
    if body.match_ids is not None:
        q = q.where(Match.id.in_(body.match_ids))
    if body.stage_id is not None:
        q = q.where(Match.stage_id == body.stage_id)
    drafts = list(await db.scalars(q))
    if not drafts:
        return {"published": 0, "notified": 0, "without_umpire": []}
    undated = [m.match_no for m in drafts if m.scheduled_at is None]
    if undated:
        raise HTTPException(422, f"Give every match a date and time before publishing (match {', '.join(map(str, undated))})")
    now = datetime.now(UTC)
    for m in drafts:
        m.published_at = now
        m.seq += 1
    await db.flush()
    teams = {t.id: t for t in await db.scalars(select(Team).where(Team.season_id == season_id))}
    next_for: dict[int, Match] = {}
    for m in drafts:  # ordered by time, so the first one seen is each team's next match
        for t in (m.team_a_id, m.team_b_id):
            next_for.setdefault(t, m)
    notified = 0
    for team_id, m in next_for.items():
        opponent = teams[m.team_b_id if m.team_a_id == team_id else m.team_a_id].name
        notified += await notify(
            db, await team_people(db, team_id), "fixtures_published", "New fixtures are published",
            f"{teams[team_id].name} play {opponent} on {_when(m.scheduled_at)} (match {m.match_no}).",
            {"link": "/fixtures", "match_id": m.id}, f"pub:{season_id}:{now.isoformat()}")
    for m in drafts:
        if m.umpire_id:
            await match_events.umpire_assigned(db, m, m.umpire_id)
    _audit(db, admin, "fixtures.publish", "season", season_id, after={"matches": [m.id for m in drafts]})
    await db.commit()
    for m in drafts:
        await publish_change(m.id, m.seq)
    await flush_outbox(db)
    return {"published": len(drafts), "notified": notified, "without_umpire": [m.match_no for m in drafts if m.umpire_id is None]}


@router.get("/seasons/{season_id}/fixtures")
async def list_fixtures(
    season_id: int,
    status: str | None = Query(default=None, pattern="^(upcoming|live|completed)$"),
    team_id: int | None = None,
    include_drafts: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[dict]:
    """The fixture list with team names, ready to show. Drafts appear only for admins who ask."""
    await _season(db, season_id)
    q = select(Match).where(Match.season_id == season_id)
    if not (include_drafts and await is_admin(db, user)):
        q = q.where(Match.published_at.is_not(None))
    if team_id is not None:
        q = q.where((Match.team_a_id == team_id) | (Match.team_b_id == team_id))
    if status == "upcoming":
        q = q.where(Match.status.in_(UPCOMING))
    elif status == "live":
        q = q.where(Match.status.in_(LIVE))
    elif status == "completed":
        q = q.where(Match.status.in_(DONE))
    matches = list(await db.scalars(q))
    teams = {t.id: t for t in await db.scalars(select(Team).where(Team.season_id == season_id))}
    ump_ids = {m.umpire_id for m in matches if m.umpire_id}
    umpires = {u.id: u.name for u in await db.scalars(select(User).where(User.id.in_(ump_ids)))} if ump_ids else {}
    far = datetime.max.replace(tzinfo=UTC)
    matches.sort(key=lambda m: (m.scheduled_at or far, m.match_no), reverse=(status == "completed"))
    return [{
        "id": m.id, "match_no": m.match_no, "round_label": m.round_label, "status": m.status, "paused": m.paused,
        "scheduled_at": m.scheduled_at.isoformat() if m.scheduled_at else None,
        "published": m.published_at is not None, "stage_id": m.stage_id,
        "team_a": {"id": m.team_a_id, "name": teams[m.team_a_id].name, "color": teams[m.team_a_id].color},
        "team_b": {"id": m.team_b_id, "name": teams[m.team_b_id].name, "color": teams[m.team_b_id].color},
        "umpire_id": m.umpire_id, "umpire": umpires.get(m.umpire_id or 0),
        "result": m.result_text, "winner_team_id": m.winner_team_id,
    } for m in matches]


@router.get("/seasons/{season_id}/stages")
async def list_stages(season_id: int, _: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_session)) -> list[dict]:
    await _season(db, season_id)
    rows = list(await db.scalars(select(Stage).where(Stage.season_id == season_id).order_by(Stage.ord)))
    totals = (await db.execute(
        select(Match.stage_id, func.count(), func.count(Match.published_at)).where(Match.season_id == season_id)
        .group_by(Match.stage_id))).all()
    counts = {stage_id: (n, published) for stage_id, n, published in totals}
    return [{"id": s.id, "kind": s.kind, "name": s.name, "ord": s.ord, "config": s.config,
             "matches": counts.get(s.id, (0, 0))[0], "published": counts.get(s.id, (0, 0))[1]} for s in rows]


@router.delete("/matches/{match_id}", status_code=204)
async def delete_match(match_id: int, admin: User = Depends(require_admin),
                       db: AsyncSession = Depends(get_session)) -> None:
    match = await db.get(Match, match_id)
    if not match:
        raise HTTPException(404, "Match not found")
    await delete_draft_match(db, match)
    _audit(db, admin, "match.delete", "match", match_id, after={"match_no": match.match_no})
    await db.commit()
