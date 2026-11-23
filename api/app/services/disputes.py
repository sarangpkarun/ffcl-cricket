"""Disputes and complaints: who may raise one, who may see and decide it, and what happens next.

Rules (see docs/PHASE4.md):
- A dispute about a match (scoring, eligibility, umpiring, other) can be raised by a captain, a vice-captain
  or the match umpire, once the match has a result and within `dispute_window_hours` of it. A conduct complaint
  can be raised by any player of the season at any time.
- One open dispute per person per match. Nothing new in an archived season.
- Seen by whoever raised it and the captains of the teams involved; admins see everything and keep private
  notes, EXCEPT an admin who belongs to a team involved (or raised it): they are a party, not a judge, and
  cannot decide it or read the private notes.
- Never public.
"""

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AuditLog,
    Dispute,
    DisputeMessage,
    Match,
    MatchResult,
    PointAdjustment,
    Season,
    Team,
    TeamMember,
    User,
)
from app.deps import is_admin
from app.services.approvals import admin_ids
from app.services.archive import ensure_open
from app.services.notify import notify
from app.services.results import season_config

MATCH_KINDS = ("scoring", "eligibility", "umpiring", "other")
KINDS = (*MATCH_KINDS, "conduct")
OPEN = ("open", "in_review")
CLOSED = ("resolved", "dismissed", "withdrawn")
ACTIONS = ("none", "result_reversed", "ball_corrected", "points_adjusted", "penalty_applied", "other")
STALE_AFTER = timedelta(hours=72)
MAX_OPEN_COMPLAINTS = 3  # conduct complaints not tied to a match, per person per season


def audit(db: AsyncSession, actor: User, action: str, d: Dispute, reason: str | None = None, after: dict | None = None) -> None:
    db.add(AuditLog(actor_id=actor.id, action=action, entity="dispute", entity_id=d.id, reason=reason, after=after))


# ---------- who is involved ----------
async def team_ids_of(db: AsyncSession, d: Dispute) -> set[int]:
    ids: set[int] = set()
    if d.match_id:
        m = await db.get(Match, d.match_id)
        if m:
            ids |= {m.team_a_id, m.team_b_id}
    if d.against_team_id:
        ids.add(d.against_team_id)
    mine = await db.scalar(select(TeamMember.team_id).join(Team, Team.id == TeamMember.team_id)
                           .where(TeamMember.user_id == d.raised_by, TeamMember.status == "approved", Team.season_id == d.season_id))
    if mine:
        ids.add(mine)
    return ids


async def members_of(db: AsyncSession, team_ids: set[int]) -> set[int]:
    """Everyone belonging to these teams: approved members and captains."""
    if not team_ids:
        return set()
    out = set(await db.scalars(select(TeamMember.user_id).where(TeamMember.team_id.in_(team_ids), TeamMember.status == "approved")))
    for t in await db.scalars(select(Team).where(Team.id.in_(team_ids))):
        if t.captain_id:
            out.add(t.captain_id)
    return out


async def leaders_of(db: AsyncSession, team_ids: set[int]) -> set[int]:
    """Captains and vice-captains: the people who speak for a team."""
    out: set[int] = set()
    for t in await db.scalars(select(Team).where(Team.id.in_(team_ids))) if team_ids else []:
        out |= {i for i in (t.captain_id, t.vice_captain_id) if i}
    return out


async def level(db: AsyncSession, user: User, d: Dispute) -> str | None:
    """"admin" (may decide), "party" (may read and reply), or None (may not see it)."""
    teams = await team_ids_of(db, d)
    if user.id == d.raised_by or user.id in await leaders_of(db, teams):
        return "party"
    if await is_admin(db, user, d.season_id):
        return None if user.id in await members_of(db, teams) else "admin"
    return None


async def judges(db: AsyncSession, d: Dispute) -> set[int]:
    """Admins who are allowed to decide this dispute."""
    return (await admin_ids(db, d.season_id)) - await members_of(db, await team_ids_of(db, d)) - {d.raised_by}


# ---------- raising ----------
async def match_window(db: AsyncSession, m: Match) -> tuple[datetime | None, datetime | None]:
    """(when the result was decided, when the window closes) for a finished match."""
    res = await db.scalar(select(MatchResult).where(MatchResult.match_id == m.id))
    if res is None:
        return None, None
    season = await db.get(Season, m.season_id)
    hours = int((await season_config(db, season))["dispute_window_hours"]) if season else 48
    return res.decided_at, res.decided_at + timedelta(hours=hours)


async def role_in_match(db: AsyncSession, user: User, m: Match) -> str | None:
    if m.umpire_id == user.id:
        return "umpire"
    for t in await db.scalars(select(Team).where(Team.id.in_([m.team_a_id, m.team_b_id]))):
        if t.captain_id == user.id:
            return "captain"
        if t.vice_captain_id == user.id:
            return "vice_captain"
    return None


async def is_player_in_season(db: AsyncSession, user: User, season_id: int) -> bool:
    return bool(await db.scalar(
        select(TeamMember.id).join(Team, Team.id == TeamMember.team_id)
        .where(TeamMember.user_id == user.id, TeamMember.status == "approved", Team.season_id == season_id).limit(1)))


async def can_raise(db: AsyncSession, user: User, m: Match, now: datetime | None = None) -> dict:
    """What this person may do about this match: {"can_raise", "reason", "role", "kinds", "deadline"}."""
    now = now or datetime.now(UTC)
    role = await role_in_match(db, user, m)
    out: dict = {"can_raise": False, "reason": None, "role": role, "kinds": [], "deadline": None}
    season = await db.get(Season, m.season_id)
    if season is not None and season.status == "archived":
        out["reason"] = "This season is archived"
        return out
    in_season = await is_player_in_season(db, user, m.season_id)
    if m.published_at is None or m.status not in ("completed", "abandoned"):
        out["reason"] = "A dispute can be raised once the match has a result"
        if in_season:
            out["kinds"] = []
        return out
    _decided, deadline = await match_window(db, m)
    out["deadline"] = deadline.isoformat() if deadline else None
    kinds: list[str] = []
    if role and deadline and now <= deadline:
        kinds += list(MATCH_KINDS)
    if in_season or role:
        kinds.append("conduct")
    if await db.scalar(select(Dispute.id).where(Dispute.match_id == m.id, Dispute.raised_by == user.id, Dispute.status.in_(OPEN))):
        out["reason"] = "You already have an open dispute about this match"
        out["kinds"] = []
        return out
    out["kinds"] = kinds
    out["can_raise"] = bool(kinds)
    if not kinds:
        out["reason"] = ("Only captains, vice-captains and the umpire can dispute a match" if not role
                         else "The time to dispute this result has passed")
    return out


async def raise_dispute(db: AsyncSession, user: User, *, kind: str, body: str, match_id: int | None = None,
                        season_id: int | None = None, against_team_id: int | None = None, now: datetime | None = None) -> Dispute:
    if kind not in KINDS:
        raise HTTPException(422, "Unknown kind of dispute")
    body = body.strip()
    raised_as, against = "player", None
    m: Match | None = None
    if match_id is not None:
        m = await db.get(Match, match_id)
        if m is None or m.published_at is None:
            raise HTTPException(404, "Match not found")
        season_id = m.season_id
    if kind in MATCH_KINDS and m is None:
        raise HTTPException(422, "Say which match this is about")
    if season_id is None:
        raise HTTPException(422, "Say which season this is about")
    season = await db.get(Season, season_id)
    if season is None:
        raise HTTPException(404, "Season not found")
    await ensure_open(db, season_id)

    if m is not None:
        allowed = await can_raise(db, user, m, now)
        if kind not in allowed["kinds"]:
            if allowed["reason"]:
                raise HTTPException(409, allowed["reason"])
            if kind in MATCH_KINDS and allowed["role"] is None:
                raise HTTPException(403, "Only captains, vice-captains and the umpire can dispute a match")
            if kind in MATCH_KINDS:
                raise HTTPException(409, "The time to dispute this result has passed")
            raise HTTPException(403, "Only players in this season can file a complaint about it")
        raised_as = allowed["role"] or "player"
        if allowed["role"] in ("captain", "vice_captain"):
            mine = await db.scalar(select(Team.id).where(Team.id.in_([m.team_a_id, m.team_b_id]),
                                                         (Team.captain_id == user.id) | (Team.vice_captain_id == user.id)))
            against = m.team_b_id if mine == m.team_a_id else m.team_a_id
    else:
        if not await is_player_in_season(db, user, season_id):
            raise HTTPException(403, "Only players in this season can file a complaint about it")
        n = await db.scalar(select(Dispute.id).where(Dispute.raised_by == user.id, Dispute.season_id == season_id,
                                                     Dispute.match_id.is_(None), Dispute.status.in_(OPEN)).offset(MAX_OPEN_COMPLAINTS - 1).limit(1))
        if n is not None:
            raise HTTPException(409, f"You already have {MAX_OPEN_COMPLAINTS} open complaints. Wait for an answer or withdraw one")
    if kind == "conduct" and against_team_id is not None:
        t = await db.get(Team, against_team_id)
        if t is None or t.season_id != season_id:
            raise HTTPException(422, "That team is not in this season")
        against = against_team_id

    d = Dispute(season_id=season_id, match_id=match_id, kind=kind, against_team_id=against, raised_by=user.id,
                raised_as=raised_as, body=body)
    db.add(d)
    await db.flush()
    audit(db, user, "dispute.raise", d, after={"kind": kind, "match_id": match_id, "season_id": season_id})
    teams = await team_ids_of(db, d)
    label = f"match {m.match_no}" if m else "a complaint"
    await notify(db, await judges(db, d), "approval", "Dispute to look at", f"{user.name} raised a {kind} dispute about {label}.",
                 {"link": f"/disputes/{d.id}"}, f"dispute:{d.id}:new:admins")
    others = (await leaders_of(db, teams)) - {user.id}
    await notify(db, others, "dispute", "A dispute was raised", f"A {kind} dispute about {label} involves your team.",
                 {"link": f"/disputes/{d.id}"}, f"dispute:{d.id}:new")
    return d


# ---------- the conversation ----------
async def participants(db: AsyncSession, d: Dispute) -> set[int]:
    """Everyone who should hear about public updates: the raiser, the captains involved and the admin looking at it."""
    people = {d.raised_by} | await leaders_of(db, await team_ids_of(db, d))
    if d.assigned_to:
        people.add(d.assigned_to)
    return people


async def add_message(db: AsyncSession, user: User, d: Dispute, body: str, internal: bool = False) -> DisputeMessage:
    lvl = await level(db, user, d)
    if lvl is None:
        raise HTTPException(404, "Dispute not found")
    if internal and lvl != "admin":
        raise HTTPException(403, "Only the admins deciding this dispute can add private notes")
    if d.status not in OPEN and not (lvl == "admin"):
        raise HTTPException(409, "This dispute is closed")
    msg = DisputeMessage(dispute_id=d.id, author_id=user.id, body=body.strip(), internal=internal)
    db.add(msg)
    d.updated_at = datetime.now(UTC)
    await db.flush()
    audit(db, user, "dispute.note" if internal else "dispute.message", d)
    if not internal:
        await notify(db, (await participants(db, d)) - {user.id}, "dispute", "New message on a dispute", f"{user.name}: {body.strip()[:120]}",
                     {"link": f"/disputes/{d.id}"}, f"dispute:{d.id}:msg:{msg.id}")
    return msg


# ---------- deciding ----------
async def _decider(db: AsyncSession, user: User, d: Dispute) -> None:
    if await level(db, user, d) != "admin":
        raise HTTPException(403, "Only an admin who is not involved can decide this dispute")


async def take(db: AsyncSession, user: User, d: Dispute) -> None:
    await _decider(db, user, d)
    if d.status not in OPEN:
        raise HTTPException(409, f"This dispute is already {d.status}")
    d.assigned_to, d.status, d.updated_at = user.id, "in_review", datetime.now(UTC)
    audit(db, user, "dispute.take", d)
    await notify(db, {d.raised_by}, "dispute", "Your dispute is being looked at", f"{user.name} is reviewing it.",
                 {"link": f"/disputes/{d.id}"}, f"dispute:{d.id}:take:{user.id}")


async def decide(db: AsyncSession, user: User, d: Dispute, *, status: str, outcome: str, action: str = "none",
                 adjustment_id: int | None = None) -> None:
    await _decider(db, user, d)
    if d.status not in OPEN:
        raise HTTPException(409, f"This dispute is already {d.status}")
    if action not in ACTIONS:
        raise HTTPException(422, "Unknown action")
    ref: dict = {"action": action}
    if action == "points_adjusted" and adjustment_id is None:
        raise HTTPException(422, "Say which points adjustment was made")
    if adjustment_id is not None:
        adj = await db.get(PointAdjustment, adjustment_id)
        if adj is None or adj.season_id != d.season_id:
            raise HTTPException(422, "That points adjustment is not in this season")
        ref["adjustment_id"] = adjustment_id
    now = datetime.now(UTC)
    d.status, d.outcome, d.resolution_ref = status, outcome.strip(), ref
    d.resolved_by, d.resolved_at, d.updated_at = user.id, now, now
    if d.assigned_to is None:
        d.assigned_to = user.id
    audit(db, user, f"dispute.{status}", d, reason=outcome.strip(), after=ref)
    word = "resolved" if status == "resolved" else "dismissed"
    await notify(db, await participants(db, d) - {user.id}, "dispute", f"Dispute {word}", outcome.strip()[:160],
                 {"link": f"/disputes/{d.id}"}, f"dispute:{d.id}:{status}")


async def reopen(db: AsyncSession, user: User, d: Dispute, reason: str) -> None:
    await _decider(db, user, d)
    if d.status in OPEN:
        raise HTTPException(409, "This dispute is already open")
    await ensure_open(db, d.season_id)
    d.status, d.assigned_to, d.updated_at = "in_review", user.id, datetime.now(UTC)
    d.resolved_at = d.resolved_by = d.outcome = d.resolution_ref = None  # type: ignore[assignment]
    db.add(DisputeMessage(dispute_id=d.id, author_id=user.id, body=f"Reopened: {reason.strip()}"))
    audit(db, user, "dispute.reopen", d, reason=reason.strip())
    await notify(db, await participants(db, d) - {user.id}, "dispute", "A dispute was reopened", reason.strip()[:160],
                 {"link": f"/disputes/{d.id}"}, f"dispute:{d.id}:reopen:{int(d.updated_at.timestamp())}")


async def withdraw(db: AsyncSession, user: User, d: Dispute) -> None:
    if user.id != d.raised_by:
        raise HTTPException(403, "Only the person who raised it can withdraw it")
    if d.status not in OPEN:
        raise HTTPException(409, f"This dispute is already {d.status}")
    d.status, d.resolved_at, d.updated_at = "withdrawn", datetime.now(UTC), datetime.now(UTC)
    audit(db, user, "dispute.withdraw", d)
    assigned = {d.assigned_to} if d.assigned_to else set()
    await notify(db, assigned, "dispute", "A dispute was withdrawn", "The person who raised it withdrew it.",
                 {"link": f"/disputes/{d.id}"}, f"dispute:{d.id}:withdrawn")


# ---------- housekeeping ----------
async def remind_stale_disputes(ctx: dict, now: datetime | None = None) -> int:
    """arq job (daily): tell the admins who may decide about disputes that have waited more than 72 hours."""
    from app.db.session import SessionLocal
    from app.services.outbox import flush

    now = now or datetime.now(UTC)
    factory = ctx.get("session_factory", SessionLocal)
    sent = 0
    async with factory() as db:
        rows = list(await db.scalars(select(Dispute).where(Dispute.status.in_(OPEN), Dispute.created_at < now - STALE_AFTER)))
        for d in rows:
            days = (now - d.created_at).days
            sent += await notify(db, await judges(db, d), "approval", f"Dispute waiting {days} days",
                                 "A dispute is still waiting for an answer.", {"link": f"/disputes/{d.id}"},
                                 f"dispute-stale:{d.id}:{now.date().isoformat()}")
        await db.commit()
        await flush(db)  # push the notifications now that they are committed
    return sent
