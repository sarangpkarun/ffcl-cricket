from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import false, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.models import Session, User, UserRole
from app.db.session import get_session

ADMIN_ROLES = {"super_admin", "tournament_admin"}


async def get_current_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_session),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing token")
    try:
        claims = decode_access_token(authorization[7:])
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from e
    sess = await db.get(Session, claims["sid"])
    if not sess or sess.revoked_at is not None or sess.expires_at < datetime.now(UTC):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session ended")
    user = await db.get(User, int(claims["sub"]))
    if not user or user.status != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account not active")
    return user


async def user_roles(db: AsyncSession, user_id: int) -> set[str]:
    rows = await db.scalars(select(UserRole.role).where(UserRole.user_id == user_id))
    return set(rows)


ROLE_MARK = "__roles__"
GLOBAL_ADMIN_MARK = "__global_admin__"
ANY_ADMIN_MARK = "__any_admin__"


def require_role(*roles: str) -> Callable[..., Awaitable[User]]:
    allowed = set(roles)

    async def dep(
        user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)
    ) -> User:
        if not (await user_roles(db, user.id) & allowed):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return user

    setattr(dep, ROLE_MARK, tuple(sorted(allowed)))  # lets a test see that a route is guarded
    return dep


@dataclass(frozen=True)
class AdminScope:
    """Where a person is an admin: everywhere, or only in some seasons."""

    is_global: bool
    seasons: frozenset[int]

    def covers(self, season_id: int | None) -> bool:
        """Global admins cover everything; a season admin covers only their own seasons; nobody covers "no season"
        unless they are global (so anything that forgets to say which season fails closed)."""
        return self.is_global or (season_id is not None and season_id in self.seasons)

    @property
    def any(self) -> bool:
        return self.is_global or bool(self.seasons)


async def admin_scope(db: AsyncSession, user_id: int) -> AdminScope:
    """super_admin, or tournament_admin without a season, is global. tournament_admin with a season is admin only there."""
    rows = (await db.execute(select(UserRole.role, UserRole.season_id).where(UserRole.user_id == user_id, UserRole.role.in_(ADMIN_ROLES)))).all()
    is_global = any(role == "super_admin" or season is None for role, season in rows)
    return AdminScope(is_global, frozenset(season for role, season in rows if role == "tournament_admin" and season is not None))


async def is_admin(db: AsyncSession, user: User, season_id: int | None = None) -> bool:
    """Is this person an admin of this season? With no season given, only global admins qualify."""
    return (await admin_scope(db, user.id)).covers(season_id)


async def admin_user_ids(db: AsyncSession, season_id: int | None = None) -> set[int]:
    """Active admins who may act on this season (global ones, plus its own). With no season: global admins only."""
    q = select(UserRole.user_id).where(UserRole.role.in_(ADMIN_ROLES), (UserRole.role == "super_admin") | UserRole.season_id.is_(None)
                                       | ((UserRole.season_id == season_id) if season_id is not None else false()))
    ids = set(await db.scalars(q))
    if not ids:
        return set()
    return set(await db.scalars(select(User.id).where(User.id.in_(ids), User.status == "active")))


async def require_admin(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> User:
    """Global admins only: people, rules, moderation, the audit log and everything that is not about one season."""
    if not (await admin_scope(db, user.id)).is_global:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
    return user


async def season_of(db: AsyncSession, by: str, params: dict[str, Any]) -> int | None:
    """The season a request is about, found from the id in its path. None if the thing does not exist."""
    from app.db.models import Dispute, Match, PointAdjustment, RosterChange, Team, UmpireDuty

    if by == "season":
        return int(params["season_id"])
    if by == "match":
        return await db.scalar(select(Match.season_id).where(Match.id == int(params["match_id"])))
    if by == "team":
        return await db.scalar(select(Team.season_id).where(Team.id == int(params["team_id"])))
    if by == "dispute":
        return await db.scalar(select(Dispute.season_id).where(Dispute.id == int(params["dispute_id"])))
    if by == "adjustment":
        return await db.scalar(select(PointAdjustment.season_id).where(PointAdjustment.id == int(params["adjustment_id"])))
    if by == "duty":
        return await db.scalar(select(Match.season_id).join(UmpireDuty, UmpireDuty.match_id == Match.id).where(UmpireDuty.id == int(params["duty_id"])))
    if by == "roster":
        return await db.scalar(select(Team.season_id).join(RosterChange, RosterChange.team_id == Team.id).where(RosterChange.id == int(params["rc_id"])))
    raise ValueError(f"unknown season resolver {by!r}")


SEASON_ADMIN_MARK = "__season_admin__"


def season_admin(by: str = "season") -> Callable[..., Awaitable[User]]:
    """Dependency: an admin of the season this request is about. A season admin passes only for their own season; a
    thing that does not exist is judged as "no season", so only global admins get as far as the 404."""

    async def dep(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> User:
        season_id = await season_of(db, by, request.path_params)
        if not (await admin_scope(db, user.id)).covers(season_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return user

    setattr(dep, SEASON_ADMIN_MARK, by)  # lets a test find every route protected this way
    return dep


setattr(require_admin, GLOBAL_ADMIN_MARK, True)


async def any_admin(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> User:
    """A global admin or an admin of at least one season: for screens that then show only what they may manage."""
    if not (await admin_scope(db, user.id)).any:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
    return user


setattr(any_admin, ANY_ADMIN_MARK, True)
