"""Walkovers and abandonments, and putting them right again.

None of these create ball events: a walkover is points only, an abandonment keeps whatever was played.
Each leaves a `MatchDeclaration` so a reversal can restore exactly what the match was before.
"""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, BallEvent, Innings, Match, MatchDeclaration, Stage, User
from app.services.announce import match_audience, say, team_names
from app.services.chat import ensure_match_rooms
from app.services.duties import sync_duty
from app.services.notify import notify
from app.services.results import advance_knockouts, clear_declared_result, set_declared_result
from app.services.schedule import remove_match, team_people

LIVE = ("innings1", "break", "innings2")
NOT_STARTED = ("scheduled", "toss", "ready")


def _link(m: Match) -> dict:
    return {"match_id": m.id, "link": f"/matches/{m.id}"}


async def _audience(db: AsyncSession, m: Match) -> set[int]:
    return await team_people(db, m.team_a_id) | await team_people(db, m.team_b_id) | await match_audience(db, m)


async def active_declaration(db: AsyncSession, match_id: int) -> MatchDeclaration | None:
    return await db.scalar(select(MatchDeclaration).where(
        MatchDeclaration.match_id == match_id, MatchDeclaration.reversed_at.is_(None)).order_by(MatchDeclaration.id.desc()).limit(1))


async def declare_walkover(db: AsyncSession, m: Match, absent_team_id: int, reason: str, by: User) -> MatchDeclaration:
    if m.status not in NOT_STARTED:
        raise HTTPException(409, "A walkover can only be declared before the match starts; abandon it instead")
    if absent_team_id not in (m.team_a_id, m.team_b_id):
        raise HTTPException(422, "The absent team must be one of the two teams in this match")
    winner = m.team_b_id if absent_team_id == m.team_a_id else m.team_a_id
    names = await team_names(db, m)
    decl = MatchDeclaration(match_id=m.id, kind="walkover", absent_team_id=absent_team_id, reason=reason,
                            prev_status=m.status, declared_by=by.id)
    db.add(decl)
    m.status, m.winner_team_id = "completed", winner
    m.result_text = f"{names[winner]} won by walkover ({names[absent_team_id]} did not turn up)"
    await set_declared_result(db, m, "walkover", winner)
    await say(db, m, f"⚠️ Walkover: {names[absent_team_id]} did not turn up. {names[winner]} are awarded the match. Reason: {reason}")
    await notify(db, await _audience(db, m), "result", "Walkover", m.result_text, _link(m), f"walkover:{m.id}:{datetime.now(UTC).timestamp()}")
    db.add(AuditLog(actor_id=by.id, action="match.walkover", entity="match", entity_id=m.id, reason=reason,
                    after={"absent": absent_team_id, "winner": winner}))
    await db.flush()
    await advance_knockouts(db, m)
    return decl


async def declare_abandon(db: AsyncSession, m: Match, reason: str, by: User, replay: bool, replay_at: datetime | None) -> MatchDeclaration:
    if m.status in ("completed", "abandoned"):
        raise HTTPException(409, "This match is already finished")
    played = await db.scalar(select(func.count()).select_from(BallEvent).join(Innings, Innings.id == BallEvent.innings_id)
                             .where(Innings.match_id == m.id)) or 0
    decl = MatchDeclaration(match_id=m.id, kind="abandoned", reason=reason, prev_status=m.status, declared_by=by.id)
    db.add(decl)
    m.status, m.paused, m.winner_team_id = "abandoned", False, None
    m.result_text = f"Match abandoned: {reason}"
    await set_declared_result(db, m, "no_result" if played else "abandoned", None)
    extra = ""
    if replay:
        number = await db.scalar(select(func.coalesce(func.max(Match.match_no), 0)).where(Match.season_id == m.season_id)) or 0
        stage = await db.get(Stage, m.stage_id) if m.stage_id else None
        # A replayed knockout keeps its place in the bracket ("Semi-final 1"); a league replay is labelled as one.
        label = m.round_label if stage is not None and stage.kind == "knockout" else f"Replay of match {m.match_no}"
        again = Match(season_id=m.season_id, match_no=number + 1, team_a_id=m.team_a_id, team_b_id=m.team_b_id,
                      umpire_id=m.umpire_id, rule_set_id=m.rule_set_id, scheduled_at=replay_at, stage_id=m.stage_id,
                      round_label=label, published_at=None)  # a draft until the admin schedules it
        db.add(again)
        await db.flush()
        await ensure_match_rooms(db, again)
        await sync_duty(db, again)
        decl.replay_match_id = again.id
        extra = " A replay will be arranged."
    await say(db, m, f"⛔ Match abandoned: {reason}.{extra}")
    await notify(db, await _audience(db, m), "result", "Match abandoned", f"{m.result_text}.{extra}", _link(m), f"abandon:{m.id}:{datetime.now(UTC).timestamp()}")
    db.add(AuditLog(actor_id=by.id, action="match.abandon", entity="match", entity_id=m.id, reason=reason,
                    after={"balls_played": played, "replay": decl.replay_match_id}))
    await db.flush()
    await advance_knockouts(db, m)
    return decl


async def reverse_declaration(db: AsyncSession, m: Match, reason: str, by: User) -> MatchDeclaration:
    decl = await active_declaration(db, m.id)
    if decl is None:
        raise HTTPException(409, "This match has no walkover or abandonment to reverse")
    if decl.replay_match_id is not None:
        again = await db.get(Match, decl.replay_match_id)
        if again is not None:
            if again.published_at is not None or again.status != "scheduled":
                raise HTTPException(409, "The replay has already been published; delete or abandon it before reversing this")
            await remove_match(db, again)  # an unpublished replay is no longer needed
    decl.reversed_at, decl.reversed_by, decl.reverse_reason = datetime.now(UTC), by.id, reason
    await clear_declared_result(db, m)
    m.status, m.winner_team_id, m.result_text = decl.prev_status, None, None
    if decl.prev_status in LIVE:
        m.paused = True  # the umpire resumes deliberately
    word = "walkover" if decl.kind == "walkover" else "abandonment"
    await say(db, m, f"🛠 An admin reversed the {word}. Reason: {reason}")
    await notify(db, await _audience(db, m), "result", "Result reversed", f"The {word} was reversed and the match is back on.",
                 _link(m), f"reverse:{decl.id}")
    db.add(AuditLog(actor_id=by.id, action="match.reverse", entity="match", entity_id=m.id, reason=reason,
                    after={"kind": decl.kind, "restored_status": decl.prev_status}))
    await db.flush()
    await advance_knockouts(db, m)
    return decl


