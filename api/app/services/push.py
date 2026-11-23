"""Browser push: who may be pushed what, and the actual sending.

Safety rules in this file:
- A subscription's endpoint is a URL the browser gave us and our server will POST to, so it is checked
  against the known push services (https, port 443, exact host families, no credentials, no IPs) and the
  sender never follows redirects. Without that, a user could point the server at internal addresses.
- A payload is built only from the notification's own title, body and an in-app link, so it can never
  carry digits or other hidden data, and a link can never leave the site.
"""

import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit

import requests
from pywebpush import WebPushException, webpush
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Notification, NotificationPref, PushSubscription
from app.db.session import SessionLocal
from app.realtime import client

log = logging.getLogger("ffcl.push")

# The push services behind Chrome/Edge/Android, Firefox, Safari and Windows. Exact hosts or their sub-domains.
ALLOWED_HOSTS = ("fcm.googleapis.com", "push.services.mozilla.com", "push.apple.com", "notify.windows.com")
MAX_FAILURES = 5
TTL_SECONDS = 600  # a push that cannot be delivered within 10 minutes is no longer useful
FG_SECONDS = 45  # how long "this person has the app open" lasts without a heartbeat

# Kinds that push by default. Chat noise (mentions, replies), every wicket and every over stay in the app
# unless a person turns them on.
PUSH_OFF_BY_DEFAULT = {"wicket", "over_complete", "mention", "reply"}
_B64URL = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")


def push_default(kind: str) -> bool:
    return kind not in PUSH_OFF_BY_DEFAULT


def endpoint_problem(endpoint: str) -> str | None:
    """Why this endpoint must not be used, or None if it is a genuine push-service address."""
    if not endpoint or len(endpoint) > 1000:
        return "Invalid push address"
    try:
        u = urlsplit(endpoint)
        port = u.port
    except ValueError:
        return "Invalid push address"
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not host or u.username or u.password or port not in (None, 443) or u.fragment:
        return "The push address must be a plain https address of a push service"
    try:
        ip_address(host)
        return "The push address must be a push service, not an IP address"
    except ValueError:
        pass
    if not any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS):
        return "That is not a known browser push service"
    return None


def keys_problem(p256dh: str, auth: str) -> str | None:
    if not (_B64URL.match(p256dh) and 80 <= len(p256dh) <= 100) or not (_B64URL.match(auth) and 16 <= len(auth) <= 40):
        return "Invalid push keys"
    return None


def safe_link(link: object) -> str:
    """Only in-app paths. Anything else (another site, a script, a protocol-relative URL) becomes the inbox."""
    if isinstance(link, str) and link.startswith("/") and not link.startswith("//") and "\\" not in link \
            and len(link) <= 200 and not re.search(r"[\x00-\x1f\x7f]", link):
        return link
    return "/notifications"


def payload_for(n: Notification) -> dict[str, Any]:
    data = n.data or {}
    return {"id": n.id, "kind": n.kind, "title": (n.title or "FFCL")[:100], "body": (n.body or "")[:200],
            "link": safe_link(data.get("link"))}


class NoRedirectSession(requests.Session):
    """A push service never needs to redirect us; following one would let an endpoint reach other hosts."""

    def request(self, method, url, **kw):  # type: ignore[no-untyped-def]
        kw["allow_redirects"] = False
        return super().request(method, url, **kw)


def send_one(sub: PushSubscription, payload: dict[str, Any]) -> int:
    """Blocking: send one push. Returns the HTTP status; raises WebPushException on a refusal."""
    if settings.push_dry_run:
        log.warning("PUSH DRY RUN user=%s payload=%s", sub.user_id, json.dumps(payload, sort_keys=True))
        return 201
    resp = webpush(
        subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
        data=json.dumps(payload), vapid_private_key=settings.vapid_private_key,
        vapid_claims={"sub": settings.vapid_subject}, ttl=TTL_SECONDS, timeout=10,
        requests_session=NoRedirectSession())
    return int(getattr(resp, "status_code", 201))


async def push_wanted(db: AsyncSession, user_id: int, kind: str) -> bool:
    pref = await db.scalar(select(NotificationPref.push).where(NotificationPref.user_id == user_id, NotificationPref.kind == kind))
    return push_default(kind) if pref is None else pref


async def in_foreground(user_id: int) -> bool:
    """True while the person has the app open and visible (their page sends a heartbeat). Fails safe: if Redis is
    down we push, because a doubled alert is better than a missed one."""
    try:
        return bool(await client().exists(f"fg:{user_id}"))
    except Exception:  # noqa: BLE001
        return False


async def deliver_to_user(db: AsyncSession, user_id: int, payload: dict[str, Any]) -> dict[str, int]:
    """Push to every device of one user, cleaning up the ones that are gone."""
    subs = list(await db.scalars(select(PushSubscription).where(PushSubscription.user_id == user_id)))
    sent = removed = failed = 0
    for sub in subs:
        try:
            await asyncio.to_thread(send_one, sub, payload)
            sub.last_success_at, sub.failures = datetime.now(UTC), 0
            sent += 1
        except WebPushException as e:
            status = getattr(e.response, "status_code", None)
            if status in (404, 410):  # the browser says this subscription no longer exists
                await db.delete(sub)
                removed += 1
                continue
            sub.failures += 1
            failed += 1
            if sub.failures >= MAX_FAILURES:
                await db.delete(sub)
                removed += 1
            log.warning("push to subscription %s failed (%s)", sub.id, status)
        except Exception:
            sub.failures += 1
            failed += 1
            log.warning("push to subscription %s crashed", sub.id, exc_info=True)
            if sub.failures >= MAX_FAILURES:
                await db.delete(sub)
                removed += 1
    await db.commit()
    return {"sent": sent, "removed": removed, "failed": failed}


async def send_push(ctx: dict, notification_id: int) -> str:
    """arq job: push one notification to its owner's devices if they want it and are not already looking at the app."""
    factory = ctx.get("session_factory", SessionLocal)
    async with factory() as db:
        n = await db.get(Notification, notification_id)
        if n is None:
            return "gone"
        if not await push_wanted(db, n.user_id, n.kind):
            return "not wanted"
        if await in_foreground(n.user_id):
            return "foreground"
        has = await db.scalar(select(PushSubscription.id).where(PushSubscription.user_id == n.user_id).limit(1))
        if has is None:
            return "no devices"
        res = await deliver_to_user(db, n.user_id, payload_for(n))
        return f"sent {res['sent']}"


async def purge_dead_subscriptions(ctx: dict, now: datetime | None = None) -> int:
    """Housekeeping: forget devices that have never worked (or not for 60 days) and keep failing."""
    from datetime import timedelta

    now = now or datetime.now(UTC)
    factory = ctx.get("session_factory", SessionLocal)
    async with factory() as db:
        res = await db.execute(delete(PushSubscription).where(
            PushSubscription.failures > 0,
            (PushSubscription.last_success_at.is_(None) & (PushSubscription.created_at < now - timedelta(days=60)))
            | (PushSubscription.last_success_at < now - timedelta(days=60))))
        await db.commit()
        return res.rowcount or 0  # type: ignore[attr-defined]
