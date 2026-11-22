from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Notification, NotificationPref, User
from app.db.session import get_session
from app.deps import get_current_user
from app.services.notify import KINDS
from app.services.outbox import notification_out

router = APIRouter(tags=["notifications"])


async def unread_count(db: AsyncSession, user_id: int) -> int:
    return (await db.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == user_id, Notification.read_at.is_(None)))) or 0


@router.get("/notifications")
async def list_notifications(before: int | None = None, limit: int = Query(default=30, ge=1, le=100),
                             user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_session)) -> dict:
    q = select(Notification).where(Notification.user_id == user.id)
    if before is not None:
        q = q.where(Notification.id < before)
    rows = list(await db.scalars(q.order_by(Notification.id.desc()).limit(limit + 1)))
    return {"notifications": [notification_out(n) for n in rows[:limit]], "has_more": len(rows) > limit,
            "unread": await unread_count(db, user.id)}


@router.get("/notifications/unread-count")
async def unread(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> dict:
    return {"unread": await unread_count(db, user.id)}


@router.post("/notifications/read-all", status_code=204)
async def read_all(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> None:
    await db.execute(update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
                     .values(read_at=datetime.now(UTC)))
    await db.commit()


@router.post("/notifications/{notification_id}/read", status_code=204)
async def mark_read(notification_id: int, user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_session)) -> None:
    n = await db.get(Notification, notification_id)
    if not n or n.user_id != user.id:  # someone else's notification looks like a missing one
        raise HTTPException(404, "Notification not found")
    if n.read_at is None:
        n.read_at = datetime.now(UTC)
        await db.commit()


@router.get("/notifications/prefs")
async def get_prefs(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> list[dict]:
    mine = {p.kind: p.in_app for p in await db.scalars(select(NotificationPref).where(NotificationPref.user_id == user.id))}
    return [{"kind": k, "label": label, "in_app": mine.get(k, default)} for k, (label, default) in KINDS.items()]


class PrefIn(BaseModel):
    kind: str
    in_app: bool


@router.put("/notifications/prefs", status_code=204)
async def set_pref(body: PrefIn, user: User = Depends(get_current_user),
                   db: AsyncSession = Depends(get_session)) -> None:
    if body.kind not in KINDS:
        raise HTTPException(422, "Unknown notification kind")
    stmt = pg_insert(NotificationPref).values(user_id=user.id, kind=body.kind, in_app=body.in_app)
    await db.execute(stmt.on_conflict_do_update(index_elements=["user_id", "kind"], set_={"in_app": body.in_app}))
    await db.commit()


