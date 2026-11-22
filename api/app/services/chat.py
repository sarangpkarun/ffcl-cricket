"""Chat access rules and message serialisation.

can_read / can_post are the ONE place that decides who may see or write in a room;
every REST endpoint and the WebSocket call them.
"""

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ChatMessage,
    ChatMute,
    ChatRead,
    ChatRoom,
    Innings,
    Match,
    MatchPlayer,
    MessageReaction,
    Over,
    Season,
    Team,
    TeamMember,
    User,
    UserRole,
)
from app.deps import ADMIN_ROLES, user_roles

MAX_BODY = 2000
EDIT_WINDOW = timedelta(minutes=15)
RATE_LIMIT = 10  # messages per window per user per room
RATE_WINDOW_SECONDS = 10
MAX_MENTIONS = 10
REACTIONS = ("👍", "❤️", "😂", "🔥", "👏", "😮", "😢", "🎉")


async def get_room(db: AsyncSession, room_id: int) -> ChatRoom:
    room = await db.get(ChatRoom, room_id)
    if not room:
        raise HTTPException(404, "Room not found")
    return room


async def _is_admin(db: AsyncSession, user: User) -> bool:
    return bool(await user_roles(db, user.id) & ADMIN_ROLES)


async def can_read(db: AsyncSession, room: ChatRoom, user: User) -> bool:
    if user.status != "active":
        return False
    if await _is_admin(db, user):
        return True
    if room.kind == "season":
        if "umpire" in await user_roles(db, user.id):
            return True
        member = await db.scalar(
            select(TeamMember.id)
            .join(Team, Team.id == TeamMember.team_id)
            .where(Team.season_id == room.season_id, TeamMember.user_id == user.id,
                   TeamMember.status == "approved")
        )
        return member is not None
    match = await db.get(Match, room.match_id) if room.match_id else None
    if not match:
        return False
    if match.umpire_id == user.id:
        return True
    if room.kind == "umpire":
        return False  # only the umpire and admins
    in_lineup = await db.scalar(
        select(MatchPlayer.id).where(MatchPlayer.match_id == match.id, MatchPlayer.user_id == user.id)
    )
    if in_lineup:
        return True
    captain = await db.scalar(
        select(Team.id).where(Team.id.in_([match.team_a_id, match.team_b_id]), Team.captain_id == user.id)
    )
    return captain is not None


async def active_mute(db: AsyncSession, season_id: int | None, user_id: int) -> ChatMute | None:
    if season_id is None:
        return None
    return await db.scalar(
        select(ChatMute).where(ChatMute.user_id == user_id, ChatMute.season_id == season_id,
                               ChatMute.lifted_at.is_(None), ChatMute.until > datetime.now(UTC))
        .order_by(ChatMute.until.desc()).limit(1)
    )


async def active_over(db: AsyncSession, match_id: int) -> Over | None:
    return await db.scalar(
        select(Over).join(Innings, Innings.id == Over.innings_id)
        .where(Innings.match_id == match_id, Innings.status == "active")
        .order_by(Over.number.desc()).limit(1))


async def submission_lock(db: AsyncSession, room: ChatRoom, user: User) -> str | None:
    """While an over's submissions are open, its batter and bowler cannot use the match chat.

    That keeps digits (and hints about them) out of the room, and stops the two from
    coordinating. Everyone else, including the umpire, chats normally.
    """
    if room.kind != "match" or not room.match_id:
        return None
    over = await active_over(db, room.match_id)
    if over and over.state == "submissions_open" and user.id in (over.bowler_id, over.batter_id):
        return "Chat is paused for you while you submit this over's digits. It reopens when submissions close."
    return None


async def post_block_reason(db: AsyncSession, room: ChatRoom, user: User) -> str | None:
    """None if the user may post; otherwise a message explaining why not."""
    if not await can_read(db, room, user):
        return "You cannot post in this room"
    mute = await active_mute(db, room.season_id, user.id)
    if mute:
        return f"You are muted until {mute.until.astimezone(UTC):%Y-%m-%d %H:%M} UTC"
    lock = await submission_lock(db, room, user)
    if lock:
        return lock
    return None


async def can_post(db: AsyncSession, room: ChatRoom, user: User) -> bool:
    return await post_block_reason(db, room, user) is None


async def is_moderator(db: AsyncSession, room: ChatRoom, user: User) -> bool:
    """Admins everywhere; the match umpire in that match's rooms."""
    if await _is_admin(db, user):
        return True
    if room.kind in ("match", "umpire") and room.match_id:
        match = await db.get(Match, room.match_id)
        return bool(match and match.umpire_id == user.id)
    return False


async def require_read(db: AsyncSession, room_id: int, user: User) -> ChatRoom:
    """404 for both 'no such room' and 'not yours', so room ids can't be probed."""
    room = await db.get(ChatRoom, room_id)
    if not room or not await can_read(db, room, user):
        raise HTTPException(404, "Room not found")
    return room


async def ensure_season_room(db: AsyncSession, season: Season) -> ChatRoom:
    key = f"season:{season.id}"
    room = await db.scalar(select(ChatRoom).where(ChatRoom.scope_key == key))
    if not room:
        room = ChatRoom(kind="season", season_id=season.id, scope_key=key)
        db.add(room)
        await db.flush()
    return room


async def ensure_match_rooms(db: AsyncSession, match: Match) -> dict[str, ChatRoom]:
    out = {}
    for kind in ("match", "umpire"):
        key = f"{kind}:{match.id}"
        room = await db.scalar(select(ChatRoom).where(ChatRoom.scope_key == key))
        if not room:
            room = ChatRoom(kind=kind, season_id=match.season_id, match_id=match.id, scope_key=key)
            db.add(room)
            await db.flush()
        out[kind] = room
    return out


async def member_ids(db: AsyncSession, room: ChatRoom) -> set[int]:
    """Everyone who can read the room. Must agree with can_read (a test checks this)."""
    admins = set(await db.scalars(select(UserRole.user_id).where(UserRole.role.in_(ADMIN_ROLES))))
    ids = set(admins)
    if room.kind == "season":
        ids |= set(await db.scalars(select(UserRole.user_id).where(UserRole.role == "umpire")))
        ids |= set(await db.scalars(
            select(TeamMember.user_id).join(Team, Team.id == TeamMember.team_id)
            .where(Team.season_id == room.season_id, TeamMember.status == "approved")))
    else:
        match = await db.get(Match, room.match_id) if room.match_id else None
        if match:
            if match.umpire_id:
                ids.add(match.umpire_id)
            if room.kind == "match":
                ids |= set(await db.scalars(select(MatchPlayer.user_id).where(MatchPlayer.match_id == match.id)))
                ids |= set(await db.scalars(select(Team.captain_id).where(
                    Team.id.in_([match.team_a_id, match.team_b_id]), Team.captain_id.is_not(None))))
    if not ids:
        return ids
    active = set(await db.scalars(select(User.id).where(User.id.in_(ids), User.status == "active")))
    return ids & active


async def readable_room_ids(db: AsyncSession, user: User) -> set[int]:
    """Set form of can_read over every room, in a handful of queries (used by search)."""
    if user.status != "active":
        return set()
    if await _is_admin(db, user):
        return set(await db.scalars(select(ChatRoom.id)))
    out: set[int] = set()
    roles = await user_roles(db, user.id)
    season_ids = set(await db.scalars(
        select(Team.season_id).join(TeamMember, TeamMember.team_id == Team.id)
        .where(TeamMember.user_id == user.id, TeamMember.status == "approved")))
    q = select(ChatRoom.id).where(ChatRoom.kind == "season")
    if "umpire" not in roles:
        q = q.where(ChatRoom.season_id.in_(season_ids or {-1}))
    out |= set(await db.scalars(q))
    lineup = select(MatchPlayer.match_id).where(MatchPlayer.user_id == user.id)
    captain = select(Match.id).join(Team, Team.id.in_([Match.team_a_id, Match.team_b_id])).where(Team.captain_id == user.id)
    umpiring = select(Match.id).where(Match.umpire_id == user.id)
    out |= set(await db.scalars(select(ChatRoom.id).where(
        ChatRoom.kind == "match", ChatRoom.match_id.in_(lineup.union(captain, umpiring)))))
    out |= set(await db.scalars(select(ChatRoom.id).where(
        ChatRoom.kind == "umpire", ChatRoom.match_id.in_(umpiring))))
    return out


async def mark_read(db: AsyncSession, room_id: int, user_id: int, last_id: int) -> int | None:
    """Move the user's read cursor forward. Returns the new cursor, or None if nothing changed."""
    newest = await db.scalar(select(ChatMessage.id).where(ChatMessage.room_id == room_id)
                             .order_by(ChatMessage.id.desc()).limit(1))
    if not newest:
        return None
    target = min(last_id, newest)
    cur = await db.scalar(select(ChatRead.last_read_id).where(ChatRead.room_id == room_id, ChatRead.user_id == user_id))
    if cur is not None and cur >= target:
        return None
    stmt = pg_insert(ChatRead).values(room_id=room_id, user_id=user_id, last_read_id=target)
    await db.execute(stmt.on_conflict_do_update(
        index_elements=["room_id", "user_id"],
        set_={"last_read_id": target, "updated_at": datetime.now(UTC)},
        where=ChatRead.last_read_id < target))
    await db.commit()
    return target


async def room_title(db: AsyncSession, room: ChatRoom) -> str:
    if room.kind == "season":
        season = await db.get(Season, room.season_id) if room.season_id else None
        return f"{season.name if season else 'Season'} chat"
    match = await db.get(Match, room.match_id) if room.match_id else None
    label = f"Match {match.match_no}" if match else "Match"
    return f"{label} chat" if room.kind == "match" else f"{label} umpire channel"


def _snippet(m: ChatMessage) -> str:
    return (m.body or "")[:100]


def message_out(msg: ChatMessage, sender: User | None, reactions: dict[str, list[int]] | None = None,
                reply: dict | None = None) -> dict:
    deleted = msg.deleted_at is not None
    return {
        "id": msg.id,
        "room_id": msg.room_id,
        "kind": msg.kind,
        "sender": {"id": sender.id, "name": sender.name, "player_code": sender.player_code}
        if sender else None,
        "body": None if deleted else msg.body,  # a removed message never leaves the server
        "meta": None if deleted else msg.meta,
        "reply_to": None if deleted else reply,
        "reactions": {} if deleted else (reactions or {}),
        "pinned": msg.pinned_at is not None and not deleted,
        "client_id": msg.client_id,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
        "edited_at": msg.edited_at.isoformat() if msg.edited_at else None,
        "deleted": deleted,
    }


async def messages_out(db: AsyncSession, msgs: list[ChatMessage]) -> list[dict]:
    if not msgs:
        return []
    ids = [m.id for m in msgs]
    rx: dict[int, dict[str, list[int]]] = {}
    for r in await db.scalars(select(MessageReaction).where(MessageReaction.message_id.in_(ids))
                              .order_by(MessageReaction.id)):
        rx.setdefault(r.message_id, {}).setdefault(r.emoji, []).append(r.user_id)
    reply_ids = {m.reply_to_id for m in msgs if m.reply_to_id}
    targets = {t.id: t for t in await db.scalars(select(ChatMessage).where(ChatMessage.id.in_(reply_ids)))} if reply_ids else {}
    user_ids = {m.sender_id for m in msgs if m.sender_id} | {t.sender_id for t in targets.values() if t.sender_id}
    users = {u.id: u for u in await db.scalars(select(User).where(User.id.in_(user_ids)))} if user_ids else {}
    out = []
    for m in msgs:
        reply = None
        if m.reply_to_id and m.reply_to_id in targets:
            t = targets[m.reply_to_id]
            gone = t.deleted_at is not None
            who = users.get(t.sender_id) if t.sender_id else None
            reply = {"id": t.id, "sender_name": who.name if who else None,
                     "snippet": None if gone else _snippet(t), "deleted": gone}
        out.append(message_out(m, users.get(m.sender_id) if m.sender_id else None, rx.get(m.id), reply))
    return out
