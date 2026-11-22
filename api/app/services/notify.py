"""In-app notifications. Browser push and email arrive in Phase 4."""

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Notification, NotificationPref
from app.services.outbox import queue_notification

# kind -> (what the user sees in settings, on by default?)
KINDS: dict[str, tuple[str, bool]] = {
    "umpire_assigned": ("I am assigned as umpire", True),
    "toss_ready": ("The toss for my match is open", True),
    "your_over": ("It is my turn to submit digits", True),
    "wicket": ("A wicket falls on my team", True),
    "over_complete": ("Every over finishes in my match", False),
    "penalty": ("A penalty hits my team", True),
    "result": ("My match has a result", True),
    "announcement": ("Announcements", True),
    "mention": ("Someone mentions me", True),
    "reply": ("Someone replies to me", True),
    "match_reminder": ("A match of mine is about to start", True),
    "toss_reminder": ("The toss is due and nobody has opened it", True),
    "deadline_alert": ("My submission deadline is close", True),
}


async def wants(db: AsyncSession, user_ids: set[int], kind: str) -> set[int]:
    """Users who should receive this kind: their own choice, else the default."""
    if not user_ids:
        return set()
    default_on = KINDS[kind][1]
    prefs = {p.user_id: p.in_app for p in await db.scalars(
        select(NotificationPref).where(NotificationPref.kind == kind, NotificationPref.user_id.in_(user_ids)))}
    return {u for u in user_ids if prefs.get(u, default_on)}


async def notify(db: AsyncSession, user_ids: Iterable[int], kind: str, title: str, body: str | None,
                 data: dict | None, dedupe_key: str) -> int:
    """Create notifications (idempotent per user, kind and dedupe_key). Returns how many were new.

    Runs inside the caller's transaction; pushing to connected clients waits for the commit.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown notification kind {kind!r}")
    created = 0
    for uid in sorted(await wants(db, set(user_ids), kind)):
        stmt = (pg_insert(Notification)
                .values(user_id=uid, kind=kind, title=title[:160], body=body, data=data or {}, dedupe_key=dedupe_key)
                .on_conflict_do_nothing(index_elements=["user_id", "kind", "dedupe_key"])
                .returning(Notification))
        row = (await db.scalars(stmt)).first()
        if row is not None:
            created += 1
            queue_notification(db, row)
    return created
