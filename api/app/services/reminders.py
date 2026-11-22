"""Scheduled notifications. Each function is safe to run as often as you like: every
notification carries a dedupe key, so a repeated or retried run never notifies twice.

`now` and the session factory can be injected so tests control time and database.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.db.models import DigitSubmission, Innings, Match, Notification, Over, Team
from app.db.session import SessionLocal
from app.services.announce import match_audience, team_names
from app.services.notify import notify
from app.services.outbox import flush

FIRST_REMINDER_MIN = 60
SECOND_REMINDER_MIN = 10
TOSS_GRACE = timedelta(hours=3)  # stop nagging about a match nobody turned up for
DEADLINE_WARNING_SECONDS = 30
READ_KEEP = timedelta(days=90)
UNREAD_KEEP = timedelta(days=365)


def _link(m: Match) -> dict:
    return {"match_id": m.id, "link": f"/matches/{m.id}"}


async def scan_reminders(ctx: dict, now: datetime | None = None) -> dict[str, int]:
    """Match starting soon (about an hour and ten minutes ahead), and "match time, no toss yet"."""
    now = now or datetime.now(UTC)
    factory = ctx.get("session_factory", SessionLocal)
    sent = {"match_reminder": 0, "toss_reminder": 0}
    async with factory() as db:
        matches = list(await db.scalars(select(Match).where(
            Match.status == "scheduled", Match.scheduled_at.is_not(None),
            Match.scheduled_at <= now + timedelta(minutes=FIRST_REMINDER_MIN),
            Match.scheduled_at > now - TOSS_GRACE)))
        for m in matches:
            assert m.scheduled_at is not None
            minutes = (m.scheduled_at - now).total_seconds() / 60
            names = await team_names(db, m)
            versus = f"{names[m.team_a_id]} vs {names[m.team_b_id]}"
            if minutes > 0:
                # a match created late only gets the reminder that still makes sense
                which = "remind10" if minutes <= SECOND_REMINDER_MIN else "remind60"
                sent["match_reminder"] += await notify(
                    db, await match_audience(db, m), "match_reminder",
                    f"Match {m.match_no} starts in {max(1, round(minutes))} min", versus, _link(m), f"{which}:{m.id}")
            else:
                officials = {i for i in (m.umpire_id,) if i}
                sent["toss_reminder"] += await notify(
                    db, await _captains(db, m) | officials, "toss_reminder", "It is match time",
                    f"{versus}: the toss has not been opened yet.", _link(m), f"toss-due:{m.id}")
        await db.commit()
        await flush(db)
    return sent


async def _captains(db, m: Match) -> set[int]:
    rows = await db.scalars(select(Team.captain_id).where(
        Team.id.in_([m.team_a_id, m.team_b_id]), Team.captain_id.is_not(None)))
    return {c for c in rows if c}


async def scan_deadlines(ctx: dict, now: datetime | None = None) -> int:
    """Warn whoever has not submitted when an over's deadline is about 30 seconds away."""
    now = now or datetime.now(UTC)
    factory = ctx.get("session_factory", SessionLocal)
    count = 0
    async with factory() as db:
        rows = await db.execute(
            select(Over, Match).join(Innings, Innings.id == Over.innings_id).join(Match, Match.id == Innings.match_id)
            .where(Over.state == "submissions_open", Match.paused.is_(False), Over.deadline_at.is_not(None),
                   Over.deadline_at > now, Over.deadline_at <= now + timedelta(seconds=DEADLINE_WARNING_SECONDS)))
        for over, m in rows.all():
            done = {s.role for s in await db.scalars(select(DigitSubmission).where(DigitSubmission.over_id == over.id))}
            waiting = {u for role, u in (("bat", over.batter_id), ("bowl", over.bowler_id)) if u and role not in done}
            count += await notify(db, waiting, "deadline_alert", "About 30 seconds left",
                                  "Submit your six digits now or the umpire will have to step in.", _link(m),
                                  f"deadline:{over.id}")
        await db.commit()
        await flush(db)
    return count


async def purge_notifications(ctx: dict, now: datetime | None = None) -> int:
    """Housekeeping: drop old read notifications (90 days) and very old unread ones (a year)."""
    now = now or datetime.now(UTC)
    factory = ctx.get("session_factory", SessionLocal)
    async with factory() as db:
        res = await db.execute(delete(Notification).where(
            ((Notification.read_at.is_not(None)) & (Notification.created_at < now - READ_KEEP))
            | (Notification.created_at < now - UNREAD_KEEP)))
        await db.commit()
        return res.rowcount or 0  # type: ignore[attr-defined]
