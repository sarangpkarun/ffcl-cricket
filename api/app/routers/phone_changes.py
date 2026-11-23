"""Changing a registered phone number: ask, an admin approves, then prove the new number with a code."""

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import otp
from app.core.config import settings
from app.core.security import sha256
from app.db.models import AuditLog, OtpCode, PhoneChangeRequest, User
from app.db.session import get_session
from app.deps import get_current_user, require_admin
from app.routers.auth import throttle
from app.services.approvals import ask_admins, mask_phone, tell
from app.services.outbox import flush as flush_outbox

router = APIRouter(tags=["phone"])
OPEN = ("pending", "approved")
TAKEN = "That number cannot be used. Try a different one."  # deliberately vague: never reveal who owns a number


class PhoneIn(BaseModel):
    new_phone: str = Field(pattern=r"^\+?[0-9]{8,15}$")
    reason: str = Field(min_length=3, max_length=500)


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class NoteIn(BaseModel):
    note: str = Field(min_length=3, max_length=500)


async def _taken(db: AsyncSession, phone: str, user_id: int) -> bool:
    if await db.scalar(select(User.id).where(User.phone == phone, User.id != user_id)):
        return True
    return bool(await db.scalar(select(PhoneChangeRequest.id).where(
        PhoneChangeRequest.new_phone == phone, PhoneChangeRequest.status.in_(OPEN), PhoneChangeRequest.user_id != user_id)))


def _mine(r: PhoneChangeRequest) -> dict:
    return {"id": r.id, "new_phone": mask_phone(r.new_phone), "status": r.status, "reason": r.reason,
            "decision_note": r.decision_note, "created_at": r.created_at.isoformat()}


async def _open(db: AsyncSession, user: User, lock: bool = False) -> PhoneChangeRequest | None:
    q = select(PhoneChangeRequest).where(PhoneChangeRequest.user_id == user.id, PhoneChangeRequest.status.in_(OPEN))
    return await db.scalar(q.with_for_update() if lock else q)


@router.post("/me/phone-change", status_code=201)
async def request_change(body: PhoneIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> dict:
    await throttle("phone-change", str(user.id), 5, 3600)
    if body.new_phone == user.phone:
        raise HTTPException(409, "That is already your number")
    if await _open(db, user):
        raise HTTPException(409, "You already have a phone change in progress")
    if await _taken(db, body.new_phone, user.id):
        raise HTTPException(409, TAKEN)
    r = PhoneChangeRequest(user_id=user.id, new_phone=body.new_phone, reason=body.reason.strip())
    db.add(r)
    await db.flush()
    db.add(AuditLog(actor_id=user.id, action="phone.request", entity="phone_change", entity_id=r.id, reason=r.reason,
                    after={"new": mask_phone(r.new_phone)}))
    await ask_admins(db, "Phone change to approve", f"{user.name} asks to change their phone number.", f"pc:{r.id}")
    await db.commit()
    await flush_outbox(db)
    return _mine(r)


@router.get("/me/phone-change")
async def my_change(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> dict | None:
    r = await db.scalar(select(PhoneChangeRequest).where(PhoneChangeRequest.user_id == user.id)
                        .order_by(PhoneChangeRequest.id.desc()).limit(1))
    return _mine(r) if r else None


@router.delete("/me/phone-change", status_code=204)
async def cancel(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> None:
    r = await _open(db, user, lock=True)
    if not r:
        raise HTTPException(404, "Nothing to cancel")
    r.status = "cancelled"
    db.add(AuditLog(actor_id=user.id, action="phone.cancel", entity="phone_change", entity_id=r.id))
    await db.commit()


@router.post("/me/phone-change/otp/request", status_code=204)
async def send_code(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> None:
    if not otp.enabled():
        raise HTTPException(409, otp.DISABLED_MESSAGE)
    r = await _open(db, user)
    if not r or r.status != "approved":
        raise HTTPException(409, "An admin has not approved this change yet")
    await throttle("otp-request", str(user.id), 3, 600)
    code = f"{secrets.randbelow(10**6):06d}"
    db.add(OtpCode(phone=r.new_phone, code_hash=sha256(code),
                   expires_at=datetime.now(UTC) + timedelta(minutes=settings.otp_ttl_minutes)))
    await db.commit()
    otp.get_provider().send(r.new_phone, code)


@router.post("/me/phone-change/verify")
async def verify(body: CodeIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> dict:
    await throttle("phone-verify", str(user.id), 10, 600)
    r = await _open(db, user, lock=True)
    if not r or r.status != "approved":
        raise HTTPException(409, "An admin has not approved this change yet")
    rec = await db.scalar(select(OtpCode).where(OtpCode.phone == r.new_phone, OtpCode.consumed_at.is_(None))
                          .order_by(OtpCode.id.desc()).limit(1))
    if not rec or rec.expires_at < datetime.now(UTC) or rec.attempts >= settings.otp_max_attempts:
        raise HTTPException(400, "Code expired or too many attempts")
    rec.attempts += 1
    if not secrets.compare_digest(rec.code_hash, sha256(body.code)):
        await db.commit()
        raise HTTPException(400, "Incorrect code")
    if await _taken(db, r.new_phone, user.id):  # someone else registered it while we waited
        await db.commit()
        raise HTTPException(409, TAKEN)
    rec.consumed_at = datetime.now(UTC)
    old = user.phone
    user.phone, user.phone_verified = r.new_phone, True
    user.phone_verified_at, user.phone_verified_by = datetime.now(UTC), None
    r.status, r.completed_at = "completed", datetime.now(UTC)
    db.add(AuditLog(actor_id=user.id, action="phone.complete", entity="phone_change", entity_id=r.id,
                    before={"phone": mask_phone(old)}, after={"phone": mask_phone(r.new_phone)}))
    await tell(db, {user.id}, "phone", "Phone number changed", "Your phone number was updated.", "/profile", f"pc:{r.id}:done")
    await db.commit()
    await flush_outbox(db)
    return {"phone": user.phone}


# ---------- admin ----------
async def _admin_rows(db: AsyncSession, rows: list[PhoneChangeRequest]) -> list[dict]:
    users = {u.id: u for u in await db.scalars(select(User).where(User.id.in_({r.user_id for r in rows})))} if rows else {}
    return [{"id": r.id, "status": r.status, "reason": r.reason, "decision_note": r.decision_note,
             "user": {"id": r.user_id, "name": users[r.user_id].name, "player_code": users[r.user_id].player_code},
             "current_phone": mask_phone(users[r.user_id].phone), "new_phone": r.new_phone,
             "created_at": r.created_at.isoformat()} for r in rows]


@router.get("/admin/phone-changes")
async def admin_list(status: str | None = Query(default=None, pattern="^(pending|approved|rejected|completed|cancelled)$"),
                     _: User = Depends(require_admin), db: AsyncSession = Depends(get_session)) -> list[dict]:
    q = select(PhoneChangeRequest).order_by(PhoneChangeRequest.id.desc()).limit(200)
    if status:
        q = q.where(PhoneChangeRequest.status == status)
    return await _admin_rows(db, list(await db.scalars(q)))


async def _pending(db: AsyncSession, rid: int) -> PhoneChangeRequest:
    r = await db.scalar(select(PhoneChangeRequest).where(PhoneChangeRequest.id == rid).with_for_update())
    if not r:
        raise HTTPException(404, "Request not found")
    if r.status != "pending":
        raise HTTPException(409, f"This request was already {r.status}")
    return r


@router.post("/admin/phone-changes/{rid}/approve")
async def admin_approve(rid: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)) -> dict:
    r = await _pending(db, rid)
    if await db.scalar(select(User.id).where(User.phone == r.new_phone)):
        raise HTTPException(409, "That number now belongs to another account")
    r.status, r.decided_by, r.decided_at = "approved", admin.id, datetime.now(UTC)
    db.add(AuditLog(actor_id=admin.id, action="phone.approve", entity="phone_change", entity_id=r.id,
                    after={"new": mask_phone(r.new_phone)}))
    if not otp.enabled():
        # No codes are sent, so the admin's approval is the verification: the new number takes effect now.
        person = await db.get(User, r.user_id)
        assert person is not None
        old = person.phone
        person.phone, person.phone_verified = r.new_phone, True
        person.phone_verified_at, person.phone_verified_by = datetime.now(UTC), admin.id
        r.status, r.completed_at = "completed", datetime.now(UTC)
        db.add(AuditLog(actor_id=admin.id, action="phone.complete", entity="phone_change", entity_id=r.id,
                        before={"phone": mask_phone(old)}, after={"phone": mask_phone(r.new_phone), "verified_by_admin": True}))
        await tell(db, {r.user_id}, "phone", "Phone number changed", "An organiser approved and verified your new number.",
                   "/profile", f"pc:{r.id}:approved")
    else:
        await tell(db, {r.user_id}, "phone", "Phone change approved",
                   "Open your profile and confirm the code we send to the new number.", "/profile", f"pc:{r.id}:approved")
    await db.commit()
    await flush_outbox(db)
    return (await _admin_rows(db, [r]))[0]


@router.post("/admin/phone-changes/{rid}/reject")
async def admin_reject(rid: int, body: NoteIn, admin: User = Depends(require_admin),
                       db: AsyncSession = Depends(get_session)) -> dict:
    r = await _pending(db, rid)
    r.status, r.decided_by, r.decided_at, r.decision_note = "rejected", admin.id, datetime.now(UTC), body.note.strip()
    db.add(AuditLog(actor_id=admin.id, action="phone.reject", entity="phone_change", entity_id=r.id, reason=body.note.strip()))
    await tell(db, {r.user_id}, "phone", "Phone change rejected", body.note.strip(), "/profile", f"pc:{r.id}:rejected")
    await db.commit()
    await flush_outbox(db)
    return (await _admin_rows(db, [r]))[0]


