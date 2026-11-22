from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChatMessage, ChatRoom, Match, User
from app.db.session import get_session
from app.deps import get_current_user
from app.realtime import publish_room
from app.services import chat as svc
from app.services.presence import online_users
from app.services.ratelimit import allow

router = APIRouter(tags=["chat"])


class SendIn(BaseModel):
    body: str = Field(max_length=svc.MAX_BODY * 2)  # real limit checked after stripping
    client_id: str = Field(min_length=8, max_length=64)

    @field_validator("body")
    @classmethod
    def _clean(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Message is empty")
        if len(v) > svc.MAX_BODY:
            raise ValueError(f"Message is longer than {svc.MAX_BODY} characters")
        return v


class EditIn(BaseModel):
    body: str

    @field_validator("body")
    @classmethod
    def _clean(cls, v: str) -> str:
        return SendIn._clean(v)  # type: ignore[attr-defined]


async def _message(db: AsyncSession, room: ChatRoom, message_id: int) -> ChatMessage:
    msg = await db.get(ChatMessage, message_id)
    if not msg or msg.room_id != room.id:
        raise HTTPException(404, "Message not found")
    return msg


@router.get("/chat/home")
async def chat_home(user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_session)) -> list[dict]:
    """Season rooms the user can read, newest season first."""
    rooms = list(await db.scalars(select(ChatRoom).where(ChatRoom.kind == "season").order_by(ChatRoom.id.desc())))
    out = []
    for room in rooms:
        if await svc.can_read(db, room, user):
            out.append({"room_id": room.id, "season_id": room.season_id, "title": await svc.room_title(db, room)})
    return out


@router.get("/matches/{match_id}/rooms")
async def match_rooms(match_id: int, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_session)) -> dict:
    match = await db.get(Match, match_id)
    if not match:
        raise HTTPException(404, "Match not found")
    rooms = await svc.ensure_match_rooms(db, match)
    await db.commit()
    out: dict = {"match": None, "umpire": None}
    for kind, room in rooms.items():
        if await svc.can_read(db, room, user):
            out[kind] = {"room_id": room.id, "title": await svc.room_title(db, room)}
    return out


@router.get("/rooms/{room_id}")
async def room_info(room_id: int, user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_session)) -> dict:
    room = await svc.require_read(db, room_id, user)
    return {
        "id": room.id, "kind": room.kind, "season_id": room.season_id, "match_id": room.match_id,
        "title": await svc.room_title(db, room),
        "can_post": await svc.can_post(db, room, user),
        "moderator": await svc.is_moderator(db, room, user),
    }


@router.get("/rooms/{room_id}/messages")
async def list_messages(
    room_id: int,
    before: int | None = None,
    after: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """before=<id>: older page (for scrolling up). after=<id>: everything newer (reconnect resync)."""
    room = await svc.require_read(db, room_id, user)
    q = select(ChatMessage).where(ChatMessage.room_id == room.id)
    if after is not None:
        rows = list(await db.scalars(q.where(ChatMessage.id > after).order_by(ChatMessage.id).limit(limit + 1)))
        more = len(rows) > limit
        rows = rows[:limit]
    else:
        if before is not None:
            q = q.where(ChatMessage.id < before)
        rows = list(await db.scalars(q.order_by(ChatMessage.id.desc()).limit(limit + 1)))
        more = len(rows) > limit
        rows = list(reversed(rows[:limit]))
    return {"messages": await svc.messages_out(db, rows), "has_more": more}


@router.post("/rooms/{room_id}/messages", status_code=201)
async def send_message(room_id: int, body: SendIn, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_session)) -> dict:
    room = await svc.require_read(db, room_id, user)
    if not await svc.can_post(db, room, user):
        raise HTTPException(403, "You cannot post in this room")
    # A retry of the same send returns the original, never a second message.
    dup = await db.scalar(select(ChatMessage).where(
        ChatMessage.room_id == room.id, ChatMessage.sender_id == user.id, ChatMessage.client_id == body.client_id))
    if dup:
        return (await svc.messages_out(db, [dup]))[0]
    if not await allow(f"rl:chat:{room.id}:{user.id}", svc.RATE_LIMIT, svc.RATE_WINDOW_SECONDS):
        raise HTTPException(429, "You are sending messages too fast")
    msg = ChatMessage(room_id=room.id, sender_id=user.id, kind="user", body=body.body, client_id=body.client_id)
    db.add(msg)
    try:
        await db.commit()
    except IntegrityError:  # two identical retries raced; return the winner
        await db.rollback()
        winner = await db.scalar(select(ChatMessage).where(
            ChatMessage.room_id == room.id, ChatMessage.sender_id == user.id,
            ChatMessage.client_id == body.client_id))
        if winner:
            return (await svc.messages_out(db, [winner]))[0]
        raise
    out = (await svc.messages_out(db, [msg]))[0]
    await publish_room(room.id, {"type": "message", "message": out})
    return out


@router.patch("/rooms/{room_id}/messages/{message_id}")
async def edit_message(room_id: int, message_id: int, body: EditIn,
                       user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_session)) -> dict:
    room = await svc.require_read(db, room_id, user)
    msg = await _message(db, room, message_id)
    if msg.sender_id != user.id or msg.kind != "user":
        raise HTTPException(403, "You can only edit your own messages")
    if msg.deleted_at:
        raise HTTPException(409, "Message was deleted")
    if datetime.now(UTC) - msg.created_at > svc.EDIT_WINDOW:
        raise HTTPException(409, "Messages can only be edited for 15 minutes")
    msg.body, msg.edited_at = body.body, datetime.now(UTC)
    await db.commit()
    out = (await svc.messages_out(db, [msg]))[0]
    await publish_room(room.id, {"type": "edited", "message": out})
    return out


@router.delete("/rooms/{room_id}/messages/{message_id}", status_code=204)
async def delete_message(room_id: int, message_id: int, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_session)) -> None:
    room = await svc.require_read(db, room_id, user)
    msg = await _message(db, room, message_id)
    if msg.sender_id != user.id and not await svc.is_moderator(db, room, user):
        raise HTTPException(403, "You can only delete your own messages")
    if msg.deleted_at:
        return
    msg.deleted_at, msg.deleted_by = datetime.now(UTC), user.id  # soft delete keeps the record
    await db.commit()
    await publish_room(room.id, {"type": "deleted", "id": msg.id, "room_id": room.id})


@router.get("/rooms/{room_id}/online")
async def online(room_id: int, user: User = Depends(get_current_user),
                 db: AsyncSession = Depends(get_session)) -> list[dict]:
    room = await svc.require_read(db, room_id, user)
    ids = await online_users(room.id)
    if not ids:
        return []
    return [{"id": u.id, "name": u.name} for u in await db.scalars(select(User).where(User.id.in_(ids)))]


