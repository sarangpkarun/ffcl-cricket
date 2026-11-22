"""Audit log viewer (admins only): filter by person, action, record and date; page with a cursor."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, User
from app.db.session import get_session
from app.deps import require_admin

router = APIRouter(tags=["audit"])


@router.get("/admin/audit")
async def audit(
    actor_id: int | None = None,
    action: str | None = Query(default=None, max_length=60),
    entity: str | None = Query(default=None, max_length=40),
    entity_id: int | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    q: str | None = Query(default=None, max_length=100, description="text in the reason"),
    before_id: int | None = Query(default=None, description="cursor: only entries older than this id"),
    limit: int = Query(default=50, ge=1, le=200),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> dict:
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit + 1)
    if actor_id is not None:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if action:
        stmt = stmt.where(AuditLog.action.startswith(action))  # "match" finds match.walkover, match.abandon...
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if entity_id is not None:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if since:
        stmt = stmt.where(AuditLog.created_at >= since)
    if until:
        stmt = stmt.where(AuditLog.created_at < until)
    if q:
        stmt = stmt.where(AuditLog.reason.ilike("%" + q.replace("%", r"\%").replace("_", r"\_") + "%", escape="\\"))
    if before_id is not None:
        stmt = stmt.where(AuditLog.id < before_id)
    rows = list(await db.scalars(stmt))
    more = len(rows) > limit
    rows = rows[:limit]
    ids = {r.actor_id for r in rows if r.actor_id}
    names = {u.id: u.name for u in await db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}
    return {
        "entries": [{"id": r.id, "at": r.created_at.isoformat(), "actor": {"id": r.actor_id, "name": names.get(r.actor_id or 0)} if r.actor_id else None,
                     "action": r.action, "entity": r.entity, "entity_id": r.entity_id, "reason": r.reason,
                     "before": r.before, "after": r.after} for r in rows],
        "next_before_id": rows[-1].id if more and rows else None,
    }


@router.get("/admin/audit/actions")
async def actions(_: User = Depends(require_admin), db: AsyncSession = Depends(get_session)) -> list[str]:
    return list(await db.scalars(select(distinct(AuditLog.action)).order_by(AuditLog.action)))
