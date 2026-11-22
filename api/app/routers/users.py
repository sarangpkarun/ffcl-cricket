from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Session, User, UserRole
from app.db.session import get_session
from app.deps import get_current_user, require_admin, require_role, user_roles
from app.schemas import RoleIn, StatusIn, UserLite

router = APIRouter(tags=["users"])


@router.get("/users", response_model=list[UserLite])
async def search_users(
    q: str = "",
    limit: int = 20,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[User]:
    stmt = select(User).order_by(User.name).limit(min(limit, 50))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(User.name.ilike(like), User.player_code.ilike(like)))
    return list(await db.scalars(stmt))


ADMIN_ROLES = ("super_admin", "tournament_admin")


@router.post("/users/{user_id}/roles", status_code=204)
async def grant_role(
    user_id: int,
    body: RoleIn,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> None:
    if body.role in ADMIN_ROLES and "super_admin" not in await user_roles(db, admin.id):
        # admin powers are only handed out by a super admin, never by a tournament admin
        raise HTTPException(403, "Only a super admin can grant admin roles")
    if not await db.get(User, user_id):
        raise HTTPException(404, "User not found")
    existing = await db.scalar(
        select(UserRole).where(
            UserRole.user_id == user_id,
            UserRole.role == body.role,
            UserRole.season_id.is_(None) if body.season_id is None else UserRole.season_id == body.season_id,
        )
    )
    if not existing:  # NULL season_id is not covered by the unique constraint
        db.add(UserRole(user_id=user_id, role=body.role, season_id=body.season_id))
        db.add(AuditLog(actor_id=admin.id, action="role.grant", entity="user", entity_id=user_id,
                        after={"role": body.role, "season_id": body.season_id}))
        await db.commit()


@router.put("/users/{user_id}/status", status_code=204)
async def set_status(
    user_id: int,
    body: StatusIn,
    admin: User = Depends(require_role("super_admin")),
    db: AsyncSession = Depends(get_session),
) -> None:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if user.id == admin.id and body.status != "active":
        raise HTTPException(400, "You cannot suspend your own account")
    before = user.status
    user.status = body.status
    if body.status != "active":
        await db.execute(
            update(Session)
            .where(Session.user_id == user_id, Session.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
    db.add(AuditLog(actor_id=admin.id, action="user.status", entity="user", entity_id=user_id,
                    before={"status": before}, after={"status": body.status}))
    await db.commit()
