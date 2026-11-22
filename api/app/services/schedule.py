"""Fixture helpers that need the database: clashes, umpire candidates, who to tell."""

from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ChatMessage,
    ChatRoom,
    Match,
    MatchDeclaration,
    MatchPlayer,
    PointAdjustment,
    Team,
    TeamMember,
    Toss,
    UmpireDuty,
    User,
    UserRole,
)
from app.deps import is_admin

# Two matches closer together than this count as overlapping (a 7-over match plus changeover).
MATCH_WINDOW = timedelta(minutes=90)
FINISHED = ("completed", "abandoned")


async def team_members(db: AsyncSession, team_ids: list[int]) -> dict[int, set[int]]:
    out: dict[int, set[int]] = {t: set() for t in team_ids}
    rows = await db.execute(select(TeamMember.team_id, TeamMember.user_id).where(
        TeamMember.team_id.in_(team_ids), TeamMember.status == "approved"))
    for team_id, user_id in rows:
        out[team_id].add(user_id)
    return out


async def team_people(db: AsyncSession, team_id: int) -> set[int]:
    """Everyone to tell about a team's fixtures: its approved members and its captain."""
    people = (await team_members(db, [team_id]))[team_id]
    team = await db.get(Team, team_id)
    if team and team.captain_id:
        people.add(team.captain_id)
    return people


async def umpire_candidates(db: AsyncSession, season_id: int) -> dict[int, int | None]:
    """Active umpires -> the team (in this season) that supplies them, or None if unaffiliated."""
    ids = set(await db.scalars(select(UserRole.user_id).where(
        UserRole.role == "umpire", (UserRole.season_id.is_(None)) | (UserRole.season_id == season_id))))
    if not ids:
        return {}
    active = set(await db.scalars(select(User.id).where(User.id.in_(ids), User.status == "active")))
    supply = {}
    rows = await db.execute(
        select(TeamMember.user_id, TeamMember.team_id).join(Team, Team.id == TeamMember.team_id)
        .where(Team.season_id == season_id, TeamMember.status == "approved", TeamMember.user_id.in_(active)))
    for user_id, team_id in rows:
        supply[user_id] = team_id
    return {u: supply.get(u) for u in sorted(active)}


async def find_conflicts(db: AsyncSession, *, season_id: int, team_ids: list[int], umpire_id: int | None,
                         when, exclude_match_id: int | None = None) -> list[str]:
    """Human-readable clashes for a proposed match time: a team, the umpire, or the umpire's own team."""
    if when is None:
        return []
    q = select(Match).where(Match.season_id == season_id, Match.scheduled_at.is_not(None),
                            Match.scheduled_at > when - MATCH_WINDOW, Match.scheduled_at < when + MATCH_WINDOW,
                            Match.status.not_in(FINISHED))
    if exclude_match_id is not None:
        q = q.where(Match.id != exclude_match_id)
    nearby = list(await db.scalars(q))
    if not nearby:
        return []
    names = {t.id: t.name for t in await db.scalars(select(Team).where(Team.season_id == season_id))}
    out: list[str] = []
    for m in nearby:
        at = m.scheduled_at.strftime("%d %b %H:%M UTC") if m.scheduled_at else ""
        for t in sorted({m.team_a_id, m.team_b_id} & set(team_ids)):
            out.append(f"{names.get(t, t)} already plays match {m.match_no} at {at}")
        if umpire_id is not None:
            if m.umpire_id == umpire_id:
                out.append(f"The umpire is already umpiring match {m.match_no} at {at}")
            members = await team_members(db, [m.team_a_id, m.team_b_id])
            if umpire_id in members[m.team_a_id] | members[m.team_b_id]:
                out.append(f"The umpire plays in match {m.match_no} at {at}")
    return out


async def ensure_visible(db: AsyncSession, user: User, match: Match) -> None:
    """Draft fixtures exist only for admins; everyone else gets "not found"."""
    if match.published_at is None and not await is_admin(db, user):
        raise HTTPException(404, "Match not found")


async def delete_draft_match(db: AsyncSession, match: Match) -> None:
    """Remove a never-published match and everything hung off it. Published matches are kept forever."""
    if match.published_at is not None or match.status != "scheduled":
        raise HTTPException(409, "Only unpublished matches can be deleted; abandon a published match instead")
    await remove_match(db, match)


async def remove_match(db: AsyncSession, match: Match) -> None:
    """Internal: delete a match that has not started, with its chat rooms, lineup and toss."""
    room_ids = list(await db.scalars(select(ChatRoom.id).where(ChatRoom.match_id == match.id)))
    if room_ids:
        await db.execute(delete(ChatMessage).where(ChatMessage.room_id.in_(room_ids)))
        await db.execute(delete(ChatRoom).where(ChatRoom.id.in_(room_ids)))
    await db.execute(delete(MatchPlayer).where(MatchPlayer.match_id == match.id))
    await db.execute(delete(Toss).where(Toss.match_id == match.id))
    await db.execute(delete(UmpireDuty).where(UmpireDuty.match_id == match.id))
    await db.execute(delete(MatchDeclaration).where(MatchDeclaration.match_id == match.id))
    await db.execute(update(PointAdjustment).where(PointAdjustment.match_id == match.id).values(match_id=None))
    await db.execute(update(MatchDeclaration).where(MatchDeclaration.replay_match_id == match.id).values(replay_match_id=None))
    await db.delete(match)
