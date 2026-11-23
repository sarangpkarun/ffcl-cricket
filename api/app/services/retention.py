"""Housekeeping: keep only what is still useful. Each job is safe to run twice and by several workers.

Retention periods (also in docs/SECURITY.md):
- one-time codes: a day after they expire
- sign-ins: until a week after they expire (a spent token is kept that long so a replay is noticed); ended sign-ins
  that were not replaced are dropped after 30 days
- invites: 90 days after they were used, revoked or expired
- audit entries: `AUDIT_RETENTION_DAYS` (default two years; 0 keeps them for ever)
- notifications: see reminders.purge_notifications
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from app.core.config import settings
from app.db.models import AuditLog, Invite, OtpCode, Session
from app.db.session import SessionLocal


async def purge_stale(ctx: dict, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(UTC)
    factory = ctx.get("session_factory", SessionLocal)
    out: dict[str, int] = {}
    async with factory() as db:
        r = await db.execute(delete(OtpCode).where(OtpCode.expires_at < now - timedelta(days=1)))
        out["otp_codes"] = r.rowcount or 0  # type: ignore[attr-defined]
        r = await db.execute(delete(Session).where(
            (Session.expires_at < now - timedelta(days=7))
            | (Session.replaced_at.is_(None) & Session.revoked_at.is_not(None) & (Session.revoked_at < now - timedelta(days=30)))))
        out["sessions"] = r.rowcount or 0  # type: ignore[attr-defined]
        cutoff = now - timedelta(days=90)
        r = await db.execute(delete(Invite).where(
            (Invite.used_at < cutoff) | (Invite.revoked_at < cutoff) | (Invite.expires_at < cutoff)))
        out["invites"] = r.rowcount or 0  # type: ignore[attr-defined]
        if settings.audit_retention_days > 0:
            r = await db.execute(delete(AuditLog).where(AuditLog.created_at < now - timedelta(days=settings.audit_retention_days)))
            out["audit"] = r.rowcount or 0  # type: ignore[attr-defined]
        await db.commit()
    return out
