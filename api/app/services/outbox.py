"""Things to announce once a transaction has committed.

System chat messages and notifications are written in the same transaction as the state
change that caused them (so they exist if and only if that change committed), but they are
only pushed to connected clients after the commit succeeds.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChatMessage, Notification
from app.realtime import publish_room, publish_user
from app.services import chat as svc

_KEY = "outbox"


def _box(db: AsyncSession) -> list:
    return db.info.setdefault(_KEY, [])


def queue_message(db: AsyncSession, msg: ChatMessage) -> None:
    _box(db).append(("msg", msg))


def queue_room_state(db: AsyncSession, room_id: int) -> None:
    item = ("room_state", room_id)
    if item not in _box(db):
        _box(db).append(item)


def queue_notification(db: AsyncSession, n: Notification) -> None:
    _box(db).append(("notif", n))


def notification_out(n: Notification) -> dict:
    return {"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "data": n.data or {},
            "created_at": n.created_at.isoformat() if n.created_at else None, "read": n.read_at is not None}


async def flush(db: AsyncSession) -> None:
    """Publish everything queued on this session. Call only after a successful commit."""
    items = db.info.pop(_KEY, [])
    for kind, x in items:
        if kind == "msg":
            out = (await svc.messages_out(db, [x]))[0]
            await publish_room(x.room_id, {"type": "message", "message": out})
        elif kind == "room_state":
            await publish_room(x, {"type": "room_state"})
        elif kind == "notif":
            await publish_user(x.user_id, {"type": "notification", "notification": notification_out(x)})
