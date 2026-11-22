"""Automatic match announcements (system chat messages) and who should hear about them."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChatMessage, ChatRoom, Match, MatchPlayer, Team, User
from app.services import chat as svc
from app.services.outbox import queue_message

_CACHE = "match_rooms"


async def rooms(db: AsyncSession, match: Match) -> dict[str, ChatRoom]:
    cache = db.info.setdefault(_CACHE, {})
    if match.id not in cache:
        cache[match.id] = await svc.ensure_match_rooms(db, match)
    return cache[match.id]


async def say(db: AsyncSession, match: Match, text: str, *, to: str = "match", meta: dict | None = None) -> ChatMessage:
    """Post a system message. `to` is "match" or "umpire". Never put hidden digits in the text."""
    room = (await rooms(db, match))[to]
    msg = ChatMessage(room_id=room.id, sender_id=None, kind="system", body=text, meta=meta)
    db.add(msg)
    await db.flush()
    queue_message(db, msg)
    return msg


async def user_names(db: AsyncSession, ids: set[int | None]) -> dict[int, str]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    return {u.id: u.name for u in await db.scalars(select(User).where(User.id.in_(wanted)))}


async def team_names(db: AsyncSession, match: Match) -> dict[int, str]:
    return {t.id: t.name for t in await db.scalars(select(Team).where(Team.id.in_([match.team_a_id, match.team_b_id])))}


async def team_audience(db: AsyncSession, match: Match, team_id: int) -> set[int]:
    """Lineup players of one team plus its captain."""
    ids = set(await db.scalars(select(MatchPlayer.user_id).where(
        MatchPlayer.match_id == match.id, MatchPlayer.team_id == team_id)))
    team = await db.get(Team, team_id)
    if team and team.captain_id:
        ids.add(team.captain_id)
    return ids


async def match_audience(db: AsyncSession, match: Match) -> set[int]:
    ids = await team_audience(db, match, match.team_a_id) | await team_audience(db, match, match.team_b_id)
    if match.umpire_id:
        ids.add(match.umpire_id)
    return ids
