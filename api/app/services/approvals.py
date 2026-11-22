"""Shared helpers for requests that need an admin's decision."""

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, UserRole
from app.deps import ADMIN_ROLES
from app.services.notify import notify


async def admin_ids(db: AsyncSession) -> set[int]:
    ids = set(await db.scalars(select(UserRole.user_id).where(UserRole.role.in_(ADMIN_ROLES))))
    if not ids:
        return set()
    return set(await db.scalars(select(User.id).where(User.id.in_(ids), User.status == "active")))


async def ask_admins(db: AsyncSession, title: str, body: str, key: str) -> None:
    await notify(db, await admin_ids(db), "approval", title, body, {"link": "/admin/approvals"}, key)


async def tell(db: AsyncSession, users: Iterable[int], kind: str, title: str, body: str, link: str, key: str) -> None:
    await notify(db, set(users), kind, title, body, {"link": link}, key)


def mask_phone(phone: str | None) -> str | None:
    """Keep the country prefix and last two digits: enough to recognise, not enough to misuse."""
    if not phone:
        return None
    return phone[:3] + "*" * max(len(phone) - 5, 0) + phone[-2:]
