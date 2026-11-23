"""Shared helpers for requests that need an admin's decision."""

from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import admin_user_ids
from app.services.notify import notify


async def admin_ids(db: AsyncSession, season_id: int | None = None) -> set[int]:
    """Admins who may decide something: global admins, plus the admins of that season when it is about one."""
    return await admin_user_ids(db, season_id)


async def ask_admins(db: AsyncSession, title: str, body: str, key: str, season_id: int | None = None) -> None:
    await notify(db, await admin_ids(db, season_id), "approval", title, body, {"link": "/admin/approvals"}, key)


async def tell(db: AsyncSession, users: Iterable[int], kind: str, title: str, body: str, link: str, key: str) -> None:
    await notify(db, set(users), kind, title, body, {"link": link}, key)


def mask_phone(phone: str | None) -> str | None:
    """Keep the country prefix and last two digits: enough to recognise, not enough to misuse."""
    if not phone:
        return None
    return phone[:3] + "*" * max(len(phone) - 5, 0) + phone[-2:]
