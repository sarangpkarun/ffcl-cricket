"""Admin user management: search the people list and take roles away safely."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Match, Team, TeamMember, User, UserRole
from app.db.session import get_session
from app.deps import admin_scope, any_admin, require_admin, season_admin, user_roles
from app.services.approvals import tell
from app.services.outbox import flush as flush_outbox

router = APIRouter(prefix="/admin", tags=["admin-users"])
ROLES = "super_admin|tournament_admin|umpire|captain|player"
ADMIN_ROLES = ("super_admin", "tournament_admin")


@router.get("/users")
async def list_users(
    q: str = "",
    role: str | None = Query(default=None, pattern=f"^({ROLES})$"),
    status: str | None = Query(default=None, pattern="^(active|suspended|banned)$"),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> dict:
    cond = []
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        cond.append(or_(User.name.ilike(like, escape="\\"), User.email.ilike(like, escape="\\"),
                        User.player_code.ilike(like, escape="\\"), User.phone.ilike(like, escape="\\")))
    if role:
        cond.append(exists().where(UserRole.user_id == User.id, UserRole.role == role))
    if status:
        cond.append(User.status == status)
    total = await db.scalar(select(func.count()).select_from(User).where(*cond)) or 0
    users = list(await db.scalars(select(User).where(*cond).order_by(User.name, User.id).limit(limit).offset(offset)))
    roles: dict[int, list[dict]] = {}
    if users:
        for r in await db.scalars(select(UserRole).where(UserRole.user_id.in_([u.id for u in users]))):
            roles.setdefault(r.user_id, []).append({"role": r.role, "season_id": r.season_id})
    return {"total": total, "users": [
        {"id": u.id, "player_code": u.player_code, "name": u.name, "email": u.email, "phone": u.phone,
         "phone_verified": u.phone_verified, "phone_verified_by_admin": u.phone_verified_by is not None, "status": u.status, "created_at": u.created_at.isoformat(),
         "roles": sorted(roles.get(u.id, []), key=lambda r: (r["role"], r["season_id"] or 0))} for u in users]}


@router.delete("/users/{user_id}/roles/{role}", status_code=204)
async def revoke_role(
    user_id: int,
    role: str,
    season_id: int | None = None,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> None:
    if role not in ROLES.split("|"):
        raise HTTPException(422, "Unknown role")
    if role in ADMIN_ROLES:
        if "super_admin" not in await user_roles(db, admin.id):
            raise HTTPException(403, "Only a super admin can remove admin roles")
        if user_id == admin.id:
            raise HTTPException(400, "You cannot remove your own admin access")
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found")
    rows = list(await db.scalars(select(UserRole).where(
        UserRole.user_id == user_id, UserRole.role == role,
        UserRole.season_id.is_(None) if season_id is None else UserRole.season_id == season_id)))
    if not rows:
        raise HTTPException(404, "That user does not have that role")
    if role == "super_admin":
        remaining = await db.scalar(select(func.count(func.distinct(UserRole.user_id))).where(
            UserRole.role == "super_admin", UserRole.user_id != user_id))
        if not remaining:
            raise HTTPException(409, "This is the last super admin; promote someone else first")
    if role == "umpire":
        open_matches = await db.scalar(select(func.count()).select_from(Match).where(
            Match.umpire_id == user_id, Match.status != "completed")) or 0
        if open_matches:
            raise HTTPException(409, f"They are the umpire of {open_matches} unfinished match(es); reassign those first")
    if role == "captain":
        leading = await db.scalar(select(Team.name).where(Team.captain_id == user_id).limit(1))
        if leading:
            raise HTTPException(409, f"They are still captain of {leading}; change the captain first")
    for r in rows:
        await db.delete(r)
    db.add(AuditLog(actor_id=admin.id, action="role.revoke", entity="user", entity_id=user_id,
                    before={"role": role, "season_id": season_id}))
    await db.commit()


class VerifyIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


@router.post("/users/{user_id}/verify-phone", status_code=204)
async def verify_phone(user_id: int, body: VerifyIn, admin: User = Depends(any_admin), db: AsyncSession = Depends(get_session)) -> None:
    """An admin vouches for someone's number (no SMS is sent). A season admin may do this only for members of their own seasons."""
    if user_id == admin.id:
        raise HTTPException(403, "You cannot verify your own number; ask another admin")
    scope = await admin_scope(db, admin.id)
    target = await db.get(User, user_id)
    if not scope.is_global:
        in_scope = target is not None and await db.scalar(
            select(TeamMember.id).join(Team, Team.id == TeamMember.team_id).where(
                TeamMember.user_id == user_id, TeamMember.status != "removed", Team.season_id.in_(scope.seasons)).limit(1))
        if not in_scope:  # the same answer whether the person does not exist or is simply not theirs to manage
            raise HTTPException(403, "Insufficient role")
    if target is None:
        raise HTTPException(404, "User not found")
    if not target.phone:
        raise HTTPException(409, "This person has not given a phone number")
    if target.phone_verified:
        raise HTTPException(409, "This number is already verified")
    target.phone_verified, target.phone_verified_at, target.phone_verified_by = True, datetime.now(UTC), admin.id
    db.add(AuditLog(actor_id=admin.id, action="phone.verify", entity="user", entity_id=user_id, reason=body.reason.strip()))
    await tell(db, {user_id}, "phone", "Your phone number is verified", "An organiser verified your number. You can now be picked for a lineup.",
               "/profile", f"verify:{user_id}:{datetime.now(UTC).timestamp()}")
    await db.commit()
    await flush_outbox(db)


@router.get("/seasons/{season_id}/unverified-phones")
async def unverified(season_id: int, _: User = Depends(season_admin("season")), db: AsyncSession = Depends(get_session)) -> list[dict]:
    """Members of this season's teams whose number nobody has verified yet."""
    rows = (await db.execute(
        select(User, Team).join(TeamMember, TeamMember.user_id == User.id).join(Team, Team.id == TeamMember.team_id)
        .where(Team.season_id == season_id, TeamMember.status != "removed", User.phone_verified.is_(False))
        .order_by(Team.name, User.name))).all()
    return [{"id": u.id, "name": u.name, "player_code": u.player_code, "phone": u.phone, "team": t.name, "team_id": t.id} for u, t in rows]
