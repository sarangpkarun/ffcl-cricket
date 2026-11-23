"""Leaving the league and taking your data with you.

Deleting an account blanks the person (name, email, phone, password) and ends every sign-in, but the row stays,
because matches, balls, awards and chat messages point at it. Everywhere the person appeared they now read
"Former player", so scorecards, tables and statistics are unchanged.
"""

import secrets
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password_async
from app.db.models import (
    AuditLog,
    ChatMessage,
    ChatRead,
    DigitSubmission,
    Dispute,
    DisputeMessage,
    Invite,
    Match,
    MatchAward,
    MatchPlayer,
    MessageReaction,
    Notification,
    NotificationPref,
    Over,
    PhoneChangeRequest,
    PushSubscription,
    RosterChange,
    Season,
    Session,
    Team,
    TeamMember,
    User,
    UserRole,
)
from app.services.results import FINISHED

FORMER = "Former player"
LIVE_SEASON = ("draft", "active")
ADMIN_ROLES = ("super_admin", "tournament_admin")


async def blockers(db: AsyncSession, user: User) -> list[str]:
    """Everything that must be handed over before this person can leave. Empty means they can go."""
    out: list[str] = []
    if await db.scalar(select(UserRole.id).where(UserRole.user_id == user.id, UserRole.role.in_(ADMIN_ROLES)).limit(1)):
        out.append("You are an admin. Ask another admin to remove your admin access first.")
    led = list(await db.scalars(
        select(Team.name).join(Season, Season.id == Team.season_id)
        .where((Team.captain_id == user.id) | (Team.vice_captain_id == user.id), Season.status.in_(LIVE_SEASON))))
    if led:
        out.append("You are captain or vice-captain of " + ", ".join(led) + ". Ask an admin to choose someone else first.")
    umpiring = list(await db.scalars(select(Match.match_no).where(Match.umpire_id == user.id, Match.status.not_in(FINISHED)).order_by(Match.match_no)))
    if umpiring:
        out.append("You are the umpire of unfinished match " + ", ".join(map(str, umpiring)) + ". Ask an admin to reassign it first.")
    playing = list(await db.scalars(
        select(Match.match_no).join(MatchPlayer, MatchPlayer.match_id == Match.id)
        .where(MatchPlayer.user_id == user.id, Match.status.not_in(FINISHED)).order_by(Match.match_no)))
    if playing:
        out.append("You are in the lineup of unfinished match " + ", ".join(map(str, playing)) + ". Ask your captain to change the lineup first.")
    return out


async def delete_account(db: AsyncSession, user: User) -> None:
    found = await blockers(db, user)
    if found:
        raise HTTPException(409, " ".join(found))
    now = datetime.now(UTC)
    uid, phone = user.id, user.phone
    # leave the teams of seasons that are still being organised; finished seasons keep their history
    live_teams = select(Team.id).join(Season, Season.id == Team.season_id).where(Season.status.in_(LIVE_SEASON))
    await db.execute(update(TeamMember).where(TeamMember.user_id == uid, TeamMember.team_id.in_(live_teams)).values(status="removed"))
    await db.execute(update(RosterChange).where(RosterChange.status == "pending", (RosterChange.out_user_id == uid) | (RosterChange.in_user_id == uid))
                     .values(status="cancelled", decided_at=now, decision_note="The person left the league"))
    await db.execute(update(PhoneChangeRequest).where(PhoneChangeRequest.user_id == uid, PhoneChangeRequest.status.in_(("pending", "approved")))
                     .values(status="cancelled"))
    if phone:
        await db.execute(update(Invite).where(Invite.phone == phone, Invite.used_at.is_(None), Invite.revoked_at.is_(None)).values(revoked_at=now))
    await db.execute(update(Session).where(Session.user_id == uid, Session.revoked_at.is_(None)).values(revoked_at=now))
    for model in (PushSubscription, Notification, NotificationPref, ChatRead, MessageReaction):
        await db.execute(delete(model).where(model.user_id == uid))
    user.name, user.email, user.phone = FORMER, f"deleted-{uid}@deleted.invalid", None
    user.password_hash = await hash_password_async(secrets.token_urlsafe(32))  # nobody knows it
    user.phone_verified, user.phone_verified_at, user.phone_verified_by = False, None, None
    user.status, user.show_publicly, user.deleted_at = "deleted", True, now
    db.add(AuditLog(actor_id=uid, action="account.delete", entity="user", entity_id=uid))


def _iso(v: datetime | None) -> str | None:
    return v.isoformat() if v else None


async def export(db: AsyncSession, user: User) -> dict:
    """Everything the league holds about this person, as plain data."""
    uid = user.id
    teams = (await db.execute(select(TeamMember, Team, Season).join(Team, Team.id == TeamMember.team_id)
                              .join(Season, Season.id == Team.season_id).where(TeamMember.user_id == uid).order_by(Season.id, Team.id))).all()
    played = (await db.execute(select(Match, Team).join(MatchPlayer, MatchPlayer.match_id == Match.id).join(Team, Team.id == MatchPlayer.team_id)
                               .where(MatchPlayer.user_id == uid).order_by(Match.id))).all()
    digits = (await db.execute(select(DigitSubmission, Over.innings_id, Over.number).join(Over, Over.id == DigitSubmission.over_id)
                               .where(DigitSubmission.user_id == uid).order_by(DigitSubmission.id).limit(5000))).all()
    disputes = list(await db.scalars(select(Dispute).where(Dispute.raised_by == uid).order_by(Dispute.id)))
    dmsgs = list(await db.scalars(select(DisputeMessage).where(DisputeMessage.author_id == uid, DisputeMessage.internal.is_(False)).order_by(DisputeMessage.id)))
    chat = list(await db.scalars(select(ChatMessage).where(ChatMessage.sender_id == uid, ChatMessage.kind == "user").order_by(ChatMessage.id).limit(5000)))
    notes = list(await db.scalars(select(Notification).where(Notification.user_id == uid).order_by(Notification.id.desc()).limit(1000)))
    pushes = list(await db.scalars(select(PushSubscription).where(PushSubscription.user_id == uid)))
    sessions = list(await db.scalars(select(Session).where(Session.user_id == uid).order_by(Session.id.desc()).limit(200)))
    audit = list(await db.scalars(select(AuditLog).where(AuditLog.actor_id == uid).order_by(AuditLog.id.desc()).limit(1000)))
    roles = list(await db.scalars(select(UserRole).where(UserRole.user_id == uid)))
    awards = list(await db.scalars(select(MatchAward).where(MatchAward.user_id == uid)))
    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "profile": {"id": uid, "player_code": user.player_code, "name": user.name, "email": user.email, "phone": user.phone,
                    "phone_verified": user.phone_verified, "phone_verified_at": _iso(user.phone_verified_at),
                    "phone_verified_by_admin": user.phone_verified_by is not None, "show_publicly": user.show_publicly,
                    "status": user.status, "created_at": _iso(user.created_at)},
        "roles": [{"role": r.role, "season_id": r.season_id} for r in roles],
        "teams": [{"team": t.name, "season": s.name, "status": m.status, "captain": t.captain_id == uid, "vice_captain": t.vice_captain_id == uid}
                  for m, t, s in teams],
        "matches_played": [{"match_id": m.id, "match_no": m.match_no, "season_id": m.season_id, "team": t.name, "scheduled_at": _iso(m.scheduled_at)} for m, t in played],
        "awards": [{"match_id": a.match_id, "kind": a.kind, "chosen_at": _iso(a.chosen_at)} for a in awards],
        "digit_submissions": [{"innings_id": i, "over": n, "role": d.role, "digits": d.digits, "submitted_at": _iso(d.submitted_at)} for d, i, n in digits],
        "disputes_raised": [{"id": d.id, "kind": d.kind, "body": d.body, "status": d.status, "created_at": _iso(d.created_at), "outcome": d.outcome} for d in disputes],
        "dispute_messages": [{"dispute_id": m.dispute_id, "body": m.body, "created_at": _iso(m.created_at)} for m in dmsgs],
        "chat_messages": [{"room_id": m.room_id, "body": None if m.deleted_at else m.body, "created_at": _iso(m.created_at)} for m in chat],
        "notifications": [{"kind": n.kind, "title": n.title, "body": n.body, "created_at": _iso(n.created_at), "read": n.read_at is not None} for n in notes],
        "push_devices": [{"device": p.user_agent, "added_at": _iso(p.created_at)} for p in pushes],
        "sign_ins": [{"device": s.user_agent, "started_at": _iso(s.created_at), "ended": s.revoked_at is not None} for s in sessions],
        "actions_you_took": [{"action": a.action, "entity": a.entity, "entity_id": a.entity_id, "reason": a.reason, "at": _iso(a.created_at)} for a in audit],
    }
