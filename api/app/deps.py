from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
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


def require_role(*roles: str) -> Callable[..., Awaitable[User]]:
    allowed = set(roles)

    async def dep(
        user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)
    ) -> User:
        if not (await user_roles(db, user.id) & allowed):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return user

    return dep


require_admin = require_role(*ADMIN_ROLES)


async def is_admin(db: AsyncSession, user: User) -> bool:
    return bool(await user_roles(db, user.id) & ADMIN_ROLES)
