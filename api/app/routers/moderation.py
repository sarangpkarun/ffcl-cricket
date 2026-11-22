"""Admin moderation: report queue and chat mutes."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, ChatMessage, ChatMute, ChatRoom, MessageReport, Season, User
from app.db.session import get_session
from app.deps import ADMIN_ROLES, require_admin, user_roles
from app.routers.chat import soft_delete
from app.services import chat as svc

router = APIRouter(prefix="/admin", tags=["moderation"])


def _audit(db: AsyncSession, actor: User, action: str, entity: str, entity_id: int, reason: str | None,
           after: dict | None = None) -> None:
    db.add(AuditLog(actor_id=actor.id, action=action, entity=entity, entity_id=entity_id, reason=reason, after=after))


@router.get("/reports")
async def list_reports(status: str = "open", admin: User = Depends(require_admin),
                       db: AsyncSession = Depends(get_session)) -> list[dict]:
    """One entry per reported message, with every report on it. Admins see removed text too."""
    reports = list(await db.scalars(select(MessageReport).where(MessageReport.status == status)
                                    .order_by(MessageReport.id)))
    by_msg: dict[int, list[MessageReport]] = {}
    for r in reports:
        by_msg.setdefault(r.message_id, []).append(r)
    out = []
    for mid, rs in by_msg.items():
        msg = await db.get(ChatMessage, mid)
        if not msg:
            continue
        room = await db.get(ChatRoom, msg.room_id)
        sender = await db.get(User, msg.sender_id) if msg.sender_id else None
        names = {u.id: u.name for u in await db.scalars(select(User).where(User.id.in_({r.reporter_id for r in rs})))}
        out.append({
            "message": {"id": msg.id, "room_id": msg.room_id, "season_id": room.season_id if room else None,
                        "room_title": await svc.room_title(db, room) if room else None,
                        "sender": {"id": sender.id, "name": sender.name} if sender else None,
                        "body": msg.body,
                        "deleted": msg.deleted_at is not None, "created_at": msg.created_at.isoformat()},
            "reports": [{"id": r.id, "reporter": names.get(r.reporter_id), "reason": r.reason,
                         "created_at": r.created_at.isoformat()} for r in rs],
            "count": len(rs),
        })
    return out


class ResolveIn(BaseModel):
    action: str = Field(pattern=r"^(dismiss|delete|delete_and_mute)$")
    mute_hours: int = Field(default=24, ge=1, le=24 * 30)


@router.post("/reports/{report_id}/resolve")
async def resolve_report(report_id: int, body: ResolveIn, admin: User = Depends(require_admin),
                         db: AsyncSession = Depends(get_session)) -> dict:
    first = await db.get(MessageReport, report_id)
    if not first:
        raise HTTPException(404, "Report not found")
    msg = await db.get(ChatMessage, first.message_id)
    room = await db.get(ChatRoom, msg.room_id) if msg else None
    if not msg or not room:
        raise HTTPException(404, "Message not found")
    open_reports = list(await db.scalars(select(MessageReport).where(
        MessageReport.message_id == msg.id, MessageReport.status == "open")))
    if not open_reports:
        raise HTTPException(409, "Already resolved")
    now = datetime.now(UTC)
    for r in open_reports:
        r.status = "dismissed" if body.action == "dismiss" else "actioned"
        r.resolved_by, r.resolved_at = admin.id, now
    _audit(db, admin, f"report.{body.action}", "chat_message", msg.id, None, {"reports": len(open_reports)})
    muted_until = None
    if body.action == "delete_and_mute" and msg.sender_id and room.season_id:
        if await user_roles(db, msg.sender_id) & ADMIN_ROLES:
            raise HTTPException(400, "Admins cannot be muted")
        muted_until = now + timedelta(hours=body.mute_hours)
        db.add(ChatMute(user_id=msg.sender_id, season_id=room.season_id, until=muted_until,
                        reason=f"Reported message #{msg.id}", created_by=admin.id))
        _audit(db, admin, "chat.mute", "user", msg.sender_id, f"Reported message #{msg.id}",
               {"season_id": room.season_id, "until": muted_until.isoformat()})
    await db.commit()
    if body.action in ("delete", "delete_and_mute"):
        await soft_delete(db, room, msg, admin)
    return {"message_id": msg.id, "resolved": len(open_reports), "muted_until": muted_until.isoformat() if muted_until else None}


class MuteIn(BaseModel):
    user_id: int
    season_id: int
    hours: int = Field(ge=1, le=24 * 30)
    reason: str = Field(min_length=3, max_length=300)


@router.post("/mutes", status_code=201)
async def create_mute(body: MuteIn, admin: User = Depends(require_admin),
                      db: AsyncSession = Depends(get_session)) -> dict:
    if not await db.get(User, body.user_id) or not await db.get(Season, body.season_id):
        raise HTTPException(404, "User or season not found")
    if await user_roles(db, body.user_id) & ADMIN_ROLES:
        raise HTTPException(400, "Admins cannot be muted")
    until = datetime.now(UTC) + timedelta(hours=body.hours)
    mute = ChatMute(user_id=body.user_id, season_id=body.season_id, until=until, reason=body.reason,
                    created_by=admin.id)
    db.add(mute)
    await db.flush()
    _audit(db, admin, "chat.mute", "user", body.user_id, body.reason,
           {"season_id": body.season_id, "until": until.isoformat()})
    await db.commit()
    return {"id": mute.id, "until": until.isoformat()}


@router.get("/mutes")
async def list_mutes(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = await db.execute(
        select(ChatMute, User).join(User, User.id == ChatMute.user_id)
        .where(ChatMute.lifted_at.is_(None), ChatMute.until > datetime.now(UTC)).order_by(ChatMute.until))
    return [{"id": m.id, "user": {"id": u.id, "name": u.name}, "season_id": m.season_id,
             "until": m.until.isoformat(), "reason": m.reason} for m, u in rows]


@router.delete("/mutes/{mute_id}", status_code=204)
async def lift_mute(mute_id: int, admin: User = Depends(require_admin),
                    db: AsyncSession = Depends(get_session)) -> None:
    mute = await db.get(ChatMute, mute_id)
    if not mute:
        raise HTTPException(404, "Mute not found")
    if mute.lifted_at is None:
        mute.lifted_at = datetime.now(UTC)
        _audit(db, admin, "chat.unmute", "user", mute.user_id, None, {"mute_id": mute.id})
        await db.commit()
