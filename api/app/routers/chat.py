from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ChatMessage,
    ChatRead,
    ChatRoom,
    Match,
    MessageReaction,
    MessageReport,
    User,
)
from app.db.session import get_session
from app.deps import get_current_user
from app.realtime import publish_room
from app.services import chat as svc
from app.services.presence import online_users
from app.services.ratelimit import allow

router = APIRouter(tags=["chat"])


def _clean_body(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("Message is empty")
    if len(v) > svc.MAX_BODY:
        raise ValueError(f"Message is longer than {svc.MAX_BODY} characters")
    return v


class SendIn(BaseModel):
    body: str = Field(max_length=svc.MAX_BODY * 2)  # real limit checked after strip
    client_id: str = Field(min_length=8, max_length=64)
    reply_to_id: int | None = None
    mentions: list[int] = Field(default_factory=list, max_length=svc.MAX_MENTIONS)

    @field_validator("body")
    @classmethod
    def _clean(cls, v: str) -> str:
        return _clean_body(v)


class EditIn(BaseModel):
    body: str

    @field_validator("body")
    @classmethod
    def _clean(cls, v: str) -> str:
        return _clean_body(v)


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
    blocked = await svc.post_block_reason(db, room, user)
    return {
        "id": room.id, "kind": room.kind, "season_id": room.season_id, "match_id": room.match_id,
        "title": await svc.room_title(db, room),
        "can_post": blocked is None,
        "blocked_reason": blocked,
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


async def _validated_extras(db: AsyncSession, room: ChatRoom, user: User, body: SendIn) -> dict:
    """Check the reply target and mentions; returns the columns to store."""
    extra: dict = {}
    if body.reply_to_id is not None:
        target = await db.get(ChatMessage, body.reply_to_id)
        if not target or target.room_id != room.id:
            raise HTTPException(422, "You can only reply to a message in this room")
        extra["reply_to_id"] = target.id
    if body.mentions:
        wanted = set(body.mentions)
        allowed = await svc.member_ids(db, room)
        if not wanted <= allowed:
            raise HTTPException(422, "You can only mention people who are in this chat")
        users = list(await db.scalars(select(User).where(User.id.in_(wanted))))
        extra["meta"] = {"mentions": [{"id": u.id, "name": u.name} for u in users]}
    return extra


@router.post("/rooms/{room_id}/messages", status_code=201)
async def send_message(room_id: int, body: SendIn, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_session)) -> dict:
    room = await svc.require_read(db, room_id, user)
    blocked = await svc.post_block_reason(db, room, user)
    if blocked:
        raise HTTPException(403, blocked)
    # A retry of the same send returns the original, never a second message.
    dup = await db.scalar(select(ChatMessage).where(
        ChatMessage.room_id == room.id, ChatMessage.sender_id == user.id, ChatMessage.client_id == body.client_id))
    if dup:
        return (await svc.messages_out(db, [dup]))[0]
    if not await allow(f"rl:chat:{room.id}:{user.id}", svc.RATE_LIMIT, svc.RATE_WINDOW_SECONDS):
        raise HTTPException(429, "You are sending messages too fast")
    extra = await _validated_extras(db, room, user, body)
    msg = ChatMessage(room_id=room.id, sender_id=user.id, body=body.body, client_id=body.client_id,
                      **({"kind": "user"} | extra))
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


async def soft_delete(db: AsyncSession, room: ChatRoom, msg: ChatMessage, by: User) -> None:
    """Hide a message from everyone (the text stays in the database for moderators)."""
    if msg.deleted_at:
        return
    msg.deleted_at, msg.deleted_by = datetime.now(UTC), by.id
    await db.commit()
    await publish_room(room.id, {"type": "deleted", "id": msg.id, "room_id": room.id})


@router.delete("/rooms/{room_id}/messages/{message_id}", status_code=204)
async def delete_message(room_id: int, message_id: int, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_session)) -> None:
    room = await svc.require_read(db, room_id, user)
    msg = await _message(db, room, message_id)
    if msg.sender_id != user.id and not await svc.is_moderator(db, room, user):
        raise HTTPException(403, "You can only delete your own messages")
    await soft_delete(db, room, msg, user)


class ReactIn(BaseModel):
    emoji: str


@router.post("/rooms/{room_id}/messages/{message_id}/reactions")
async def toggle_reaction(room_id: int, message_id: int, body: ReactIn,
                          user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_session)) -> dict:
    room = await svc.require_read(db, room_id, user)
    blocked = await svc.post_block_reason(db, room, user)
    if blocked:
        raise HTTPException(403, blocked)
    if body.emoji not in svc.REACTIONS:
        raise HTTPException(422, "That reaction is not available")
    msg = await _message(db, room, message_id)
    if msg.deleted_at:
        raise HTTPException(409, "Message was deleted")
    if not await allow(f"rl:react:{room.id}:{user.id}", 30, 10):
        raise HTTPException(429, "Slow down")
    mine = await db.scalar(select(MessageReaction).where(
        MessageReaction.message_id == msg.id, MessageReaction.user_id == user.id,
        MessageReaction.emoji == body.emoji))
    if mine:
        await db.delete(mine)
    else:
        db.add(MessageReaction(message_id=msg.id, user_id=user.id, emoji=body.emoji))
    try:
        await db.commit()
    except IntegrityError:  # double tap raced: the reaction already exists, which is the intent
        await db.rollback()
    reactions = (await svc.messages_out(db, [msg]))[0]["reactions"]
    await publish_room(room.id, {"type": "reaction", "message_id": msg.id, "reactions": reactions})
    return {"message_id": msg.id, "reactions": reactions}


async def _set_pin(db: AsyncSession, room_id: int, message_id: int, user: User, pinned: bool) -> dict:
    room = await svc.require_read(db, room_id, user)
    if not await svc.is_moderator(db, room, user):
        raise HTTPException(403, "Only admins or the match umpire can pin messages")
    msg = await _message(db, room, message_id)
    if msg.deleted_at:
        raise HTTPException(409, "Message was deleted")
    msg.pinned_at, msg.pinned_by = (datetime.now(UTC), user.id) if pinned else (None, None)
    await db.commit()
    out = (await svc.messages_out(db, [msg]))[0]
    await publish_room(room.id, {"type": "pinned", "message": out})
    return out


@router.post("/rooms/{room_id}/messages/{message_id}/pin")
async def pin_message(room_id: int, message_id: int, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_session)) -> dict:
    return await _set_pin(db, room_id, message_id, user, True)


@router.delete("/rooms/{room_id}/messages/{message_id}/pin")
async def unpin_message(room_id: int, message_id: int, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_session)) -> dict:
    return await _set_pin(db, room_id, message_id, user, False)


@router.get("/rooms/{room_id}/pinned")
async def pinned_messages(room_id: int, user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_session)) -> list[dict]:
    room = await svc.require_read(db, room_id, user)
    rows = list(await db.scalars(
        select(ChatMessage).where(ChatMessage.room_id == room.id, ChatMessage.pinned_at.is_not(None),
                                  ChatMessage.deleted_at.is_(None))
        .order_by(ChatMessage.pinned_at.desc()).limit(5)))
    return await svc.messages_out(db, rows)


class AnnounceIn(BaseModel):
    body: str

    @field_validator("body")
    @classmethod
    def _clean(cls, v: str) -> str:
        return _clean_body(v)


@router.post("/rooms/{room_id}/announcements", status_code=201)
async def announce(room_id: int, body: AnnounceIn, user: User = Depends(get_current_user),
                   db: AsyncSession = Depends(get_session)) -> dict:
    room = await svc.require_read(db, room_id, user)
    if not await svc.is_moderator(db, room, user):
        raise HTTPException(403, "Only admins or the match umpire can post announcements")
    msg = ChatMessage(room_id=room.id, sender_id=user.id, kind="announcement", body=body.body,
                      pinned_at=datetime.now(UTC), pinned_by=user.id)
    db.add(msg)
    await db.commit()
    out = (await svc.messages_out(db, [msg]))[0]
    await publish_room(room.id, {"type": "message", "message": out})
    return out


class ReportIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/rooms/{room_id}/messages/{message_id}/report", status_code=201)
async def report_message(room_id: int, message_id: int, body: ReportIn,
                         user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_session)) -> dict:
    room = await svc.require_read(db, room_id, user)
    msg = await _message(db, room, message_id)
    if msg.kind != "user" or msg.deleted_at:
        raise HTTPException(409, "That message cannot be reported")
    if msg.sender_id == user.id:
        raise HTTPException(400, "You cannot report your own message")
    existing = await db.scalar(select(MessageReport).where(
        MessageReport.message_id == msg.id, MessageReport.reporter_id == user.id))
    if existing:
        return {"id": existing.id, "duplicate": True}
    if not await allow(f"rl:report:{user.id}", 5, 60):
        raise HTTPException(429, "Too many reports; try again in a minute")
    rep = MessageReport(message_id=msg.id, reporter_id=user.id, reason=body.reason.strip())
    db.add(rep)
    await db.commit()
    return {"id": rep.id, "duplicate": False}


@router.get("/chat/reactions")
async def reaction_set(_: User = Depends(get_current_user)) -> dict:
    return {"reactions": list(svc.REACTIONS)}


@router.get("/rooms/{room_id}/members")
async def members(room_id: int, q: str = "", user: User = Depends(get_current_user),
                  db: AsyncSession = Depends(get_session)) -> list[dict]:
    """People who can be @mentioned in this room."""
    room = await svc.require_read(db, room_id, user)
    ids = (await svc.member_ids(db, room)) - {user.id}
    if not ids:
        return []
    stmt = select(User).where(User.id.in_(ids)).order_by(User.name).limit(20)
    if q:
        stmt = stmt.where(User.name.ilike(f"%{q.replace('%', '').replace('_', '')}%"))
    return [{"id": u.id, "name": u.name, "player_code": u.player_code} for u in await db.scalars(stmt)]


class ReadIn(BaseModel):
    last_id: int = Field(ge=1)


@router.post("/rooms/{room_id}/read", status_code=204)
async def read_up_to(room_id: int, body: ReadIn, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_session)) -> None:
    room = await svc.require_read(db, room_id, user)
    cursor = await svc.mark_read(db, room.id, user.id, body.last_id)
    if cursor:
        await publish_room(room.id, {"type": "read", "user": {"id": user.id, "name": user.name},
                                     "last_id": cursor})


@router.get("/rooms/{room_id}/reads")
async def reads(room_id: int, user: User = Depends(get_current_user),
                db: AsyncSession = Depends(get_session)) -> list[dict]:
    room = await svc.require_read(db, room_id, user)
    rows = await db.execute(select(ChatRead, User).join(User, User.id == ChatRead.user_id)
                            .where(ChatRead.room_id == room.id))
    return [{"user_id": u.id, "name": u.name, "last_read_id": r.last_read_id} for r, u in rows]


@router.get("/chat/search")
async def search(q: str = Query(min_length=2, max_length=100), room_id: int | None = None,
                 limit: int = Query(default=30, ge=1, le=50), user: User = Depends(get_current_user),
                 db: AsyncSession = Depends(get_session)) -> list[dict]:
    """Substring search, restricted to rooms this user can read."""
    allowed = await svc.readable_room_ids(db, user)
    if room_id is not None:
        if room_id not in allowed:
            raise HTTPException(404, "Room not found")
        allowed = {room_id}
    if not allowed:
        return []
    like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = list(await db.scalars(
        select(ChatMessage).where(ChatMessage.room_id.in_(allowed), ChatMessage.deleted_at.is_(None),
                                  ChatMessage.body.ilike(like, escape="\\"))
        .order_by(ChatMessage.id.desc()).limit(limit)))
    out = await svc.messages_out(db, rows)
    titles = {r.id: await svc.room_title(db, r) for r in await db.scalars(
        select(ChatRoom).where(ChatRoom.id.in_({m.room_id for m in rows})))} if rows else {}
    kinds = {r.id: r.kind for r in await db.scalars(select(ChatRoom).where(ChatRoom.id.in_(titles)))} if titles else {}
    return [{**m, "room": {"id": m["room_id"], "title": titles.get(m["room_id"]), "kind": kinds.get(m["room_id"])}} for m in out]


@router.get("/rooms/{room_id}/online")
async def online(room_id: int, user: User = Depends(get_current_user),
                 db: AsyncSession = Depends(get_session)) -> list[dict]:
    room = await svc.require_read(db, room_id, user)
    ids = await online_users(room.id)
    if not ids:
        return []
    return [{"id": u.id, "name": u.name} for u in await db.scalars(select(User).where(User.id.in_(ids)))]


