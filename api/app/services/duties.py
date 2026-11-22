"""Umpire duty: who was meant to umpire, which team supplied them, and whether they turned up.

A team that supplies an umpire who then fails to appear loses points (`umpire_duty_penalty` in the rule
set, default 1). The penalty is an ordinary point adjustment, so it shows on the table and can be voided.
"""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AuditLog,
    Match,
    PointAdjustment,
    Season,
    Team,
    TeamMember,
    UmpireDuty,
    User,
)
from app.services.announce import say
from app.services.notify import notify
from app.services.results import season_config
from app.services.schedule import team_people


async def supplying_team(db: AsyncSession, season_id: int, user_id: int) -> int | None:
    """The team (in this season) the umpire plays for, if any."""
    return await db.scalar(
        select(TeamMember.team_id).join(Team, Team.id == TeamMember.team_id)
        .where(Team.season_id == season_id, TeamMember.user_id == user_id, TeamMember.status == "approved")
        .order_by(TeamMember.id).limit(1))


async def sync_duty(db: AsyncSession, match: Match) -> None:
    """Keep the duty records in step with the match's umpire: swapping umpires marks the old one replaced."""
    rows = list(await db.scalars(select(UmpireDuty).where(UmpireDuty.match_id == match.id)))
    current = next((r for r in rows if r.umpire_id == match.umpire_id), None) if match.umpire_id else None
    for r in rows:
        if r is not current and r.status == "assigned":
            r.status = "replaced"  # swapped out before the match: no penalty
    if match.umpire_id and current is None:
        db.add(UmpireDuty(match_id=match.id, umpire_id=match.umpire_id, status="assigned",
                          team_id=await supplying_team(db, match.season_id, match.umpire_id)))
    elif current is not None and current.status == "replaced":
        current.status = "assigned"  # assigned back again


async def mark_performed(db: AsyncSession, match: Match, user: User) -> None:
    """The assigned umpire started the match, so they turned up."""
    if match.umpire_id != user.id:
        return
    duty = await db.scalar(select(UmpireDuty).where(UmpireDuty.match_id == match.id, UmpireDuty.umpire_id == user.id))
    if duty is not None and duty.status == "assigned":
        duty.status, duty.decided_by, duty.decided_at = "performed", user.id, datetime.now(UTC)


async def get_duty(db: AsyncSession, duty_id: int) -> UmpireDuty:
    duty = await db.get(UmpireDuty, duty_id)
    if duty is None:
        raise HTTPException(404, "Duty not found")
    return duty


async def mark_missed(db: AsyncSession, duty: UmpireDuty, by: User, reason: str) -> PointAdjustment | None:
    if duty.status == "missed":
        raise HTTPException(409, "This duty is already recorded as missed")
    match = await db.get(Match, duty.match_id)
    assert match is not None
    season = await db.get(Season, match.season_id)
    assert season is not None
    penalty = int((await season_config(db, season)).get("umpire_duty_penalty", 1))
    duty.status, duty.note, duty.decided_by, duty.decided_at = "missed", reason, by.id, datetime.now(UTC)
    adj = None
    if duty.team_id and penalty:
        adj = PointAdjustment(season_id=season.id, team_id=duty.team_id, match_id=match.id, points=-penalty,
                              kind="umpire_duty", reason=f"Umpire duty missed in match {match.match_no}: {reason}",
                              created_by=by.id)
        db.add(adj)
        await db.flush()
        duty.adjustment_id = adj.id
    db.add(AuditLog(actor_id=by.id, action="duty.missed", entity="umpire_duty", entity_id=duty.id, reason=reason,
                    after={"match": match.id, "umpire": duty.umpire_id, "team": duty.team_id, "points": -penalty if adj else 0}))
    people = {duty.umpire_id} | (await team_people(db, duty.team_id) if duty.team_id else set())
    body = f"Match {match.match_no}: umpire duty recorded as missed." + (f" {penalty} point{'' if penalty == 1 else 's'} deducted from the supplying team." if adj else "")
    await notify(db, people, "duty", "Umpire duty missed", body, {"link": "/standings"}, f"duty:{duty.id}:missed:{datetime.now(UTC).timestamp()}")
    await say(db, match, f"⚠️ The assigned umpire did not turn up. Reason: {reason}", to="umpire")
    return adj


async def reverse_missed(db: AsyncSession, duty: UmpireDuty, by: User, reason: str) -> None:
    if duty.status != "missed":
        raise HTTPException(409, "This duty is not recorded as missed")
    if duty.adjustment_id:
        adj = await db.get(PointAdjustment, duty.adjustment_id)
        if adj is not None and adj.voided_at is None:
            adj.voided_at = datetime.now(UTC)
    duty.status, duty.decided_by, duty.decided_at = "assigned", by.id, datetime.now(UTC)
    db.add(AuditLog(actor_id=by.id, action="duty.reversed", entity="umpire_duty", entity_id=duty.id, reason=reason))
    match = await db.get(Match, duty.match_id)
    assert match is not None
    people = {duty.umpire_id} | (await team_people(db, duty.team_id) if duty.team_id else set())
    await notify(db, people, "duty", "Umpire duty restored", f"Match {match.match_no}: the missed-duty record was reversed.",
                 {"link": "/standings"}, f"duty:{duty.id}:reversed:{datetime.now(UTC).timestamp()}")
    await say(db, match, f"🛠 An admin reversed the missed-duty record. Reason: {reason}", to="umpire")
