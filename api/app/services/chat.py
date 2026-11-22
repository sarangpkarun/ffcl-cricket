"""Chat access rules and message serialisation.

can_read / can_post are the ONE place that decides who may see or write in a room;
every REST endpoint and the WebSocket call them.
"""

from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ChatMessage,
    ChatRoom,
    Match,
    MatchPlayer,
    Season,
    Team,
    TeamMember,
    User,
)
from app.deps import ADMIN_ROLES, user_roles

MAX_BODY = 2000
EDIT_WINDOW = timedelta(minutes=15)
RATE_LIMIT = 10  # messages per window per user per room
RATE_WINDOW_SECONDS = 10


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


async def can_post(db: AsyncSession, room: ChatRoom, user: User) -> bool:
    # Sprint 6 adds mutes; Sprint 7 adds the batter/bowler lock while submissions are open.
    return await can_read(db, room, user)


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


async def room_title(db: AsyncSession, room: ChatRoom) -> str:
    if room.kind == "season":
        season = await db.get(Season, room.season_id) if room.season_id else None
        return f"{season.name if season else 'Season'} chat"
    match = await db.get(Match, room.match_id) if room.match_id else None
    label = f"Match {match.match_no}" if match else "Match"
    return f"{label} chat" if room.kind == "match" else f"{label} umpire channel"


def message_out(msg: ChatMessage, sender: User | None) -> dict:
    deleted = msg.deleted_at is not None
    return {
        "id": msg.id,
        "room_id": msg.room_id,
        "kind": msg.kind,
        "sender": {"id": sender.id, "name": sender.name, "player_code": sender.player_code}
        if sender else None,
        "body": None if deleted else msg.body,  # a removed message never leaves the server
        "meta": None if deleted else msg.meta,
        "client_id": msg.client_id,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
        "edited_at": msg.edited_at.isoformat() if msg.edited_at else None,
        "deleted": deleted,
    }


async def messages_out(db: AsyncSession, msgs: list[ChatMessage]) -> list[dict]:
    ids = {m.sender_id for m in msgs if m.sender_id}
    users = {u.id: u for u in await db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}
    return [message_out(m, users.get(m.sender_id) if m.sender_id else None) for m in msgs]


