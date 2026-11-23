"""Devices that receive browser push: register, list, remove, and send yourself a test."""

from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import PushSubscription, User
from app.db.session import get_session
from app.deps import get_current_user
from app.routers.auth import throttle
from app.services import push as svc

router = APIRouter(tags=["push"])


class Keys(BaseModel):
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=100)


class SubscribeIn(BaseModel):
    endpoint: str = Field(max_length=1000)
    keys: Keys


class RemoveIn(BaseModel):
    endpoint: str = Field(max_length=1000)


def _row(s: PushSubscription) -> dict:
    host = urlsplit(s.endpoint).hostname or ""
    return {"id": s.id, "service": host, "user_agent": s.user_agent, "created_at": s.created_at.isoformat(),
            "last_success_at": s.last_success_at.isoformat() if s.last_success_at else None, "failures": s.failures}


@router.get("/push/key")
async def push_key() -> dict:
    """The public half of the server's push identity. Browsers need it to subscribe."""
    on = settings.push_enabled and bool(settings.vapid_public_key)
    return {"enabled": on, "key": settings.vapid_public_key if on else None}


@router.post("/me/push/subscriptions", status_code=201)
async def subscribe(body: SubscribeIn, request: Request, user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_session)) -> dict:
    if not settings.push_enabled:
        raise HTTPException(409, "Push notifications are not switched on for this server")
    await throttle("push-subscribe", str(user.id), 20, 3600)
    problem = svc.endpoint_problem(body.endpoint) or svc.keys_problem(body.keys.p256dh, body.keys.auth)
    if problem:
        raise HTTPException(422, problem)
    ua = (request.headers.get("user-agent") or "")[:300] or None
    existing = await db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint).with_for_update())
    if existing is None:
        count = await db.scalar(select(func.count()).select_from(PushSubscription).where(PushSubscription.user_id == user.id))
        if (count or 0) >= settings.push_max_devices_per_user:
            raise HTTPException(409, f"You already have {settings.push_max_devices_per_user} devices. Remove one first")
        existing = PushSubscription(user_id=user.id, endpoint=body.endpoint, p256dh=body.keys.p256dh, auth=body.keys.auth, user_agent=ua)
        db.add(existing)
    else:  # the same browser again (maybe a different person on a shared device): it now belongs to whoever is signed in
        existing.user_id, existing.p256dh, existing.auth, existing.user_agent = user.id, body.keys.p256dh, body.keys.auth, ua
        existing.failures = 0
    await db.commit()
    return _row(existing)


@router.get("/me/push/subscriptions")
async def my_devices(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = await db.scalars(select(PushSubscription).where(PushSubscription.user_id == user.id).order_by(PushSubscription.id))
    return [_row(s) for s in rows]


@router.post("/me/push/subscriptions/remove", status_code=204)
async def remove_by_endpoint(body: RemoveIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> None:
    sub = await db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint, PushSubscription.user_id == user.id))
    if sub:  # removing something already gone is fine
        await db.delete(sub)
        await db.commit()


@router.delete("/me/push/subscriptions/{sub_id}", status_code=204)
async def remove_device(sub_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> None:
    sub = await db.scalar(select(PushSubscription).where(PushSubscription.id == sub_id, PushSubscription.user_id == user.id))
    if not sub:
        raise HTTPException(404, "Device not found")
    await db.delete(sub)
    await db.commit()


@router.post("/me/push/test")
async def send_test(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> dict:
    """Push a harmless message to all of your devices right now, so you can see that it works."""
    if not settings.push_enabled:
        raise HTTPException(409, "Push notifications are not switched on for this server")
    await throttle("push-test", str(user.id), 5, 600)
    has = await db.scalar(select(PushSubscription.id).where(PushSubscription.user_id == user.id).limit(1))
    if has is None:
        raise HTTPException(409, "No device is registered. Turn on push notifications on this device first")
    payload = {"id": 0, "kind": "test", "title": "FFCL test notification", "body": "Push notifications work on this device.",
               "link": "/notifications", "at": datetime.now(UTC).isoformat()}
    return await svc.deliver_to_user(db, user.id, payload)
