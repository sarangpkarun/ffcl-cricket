"""Phase 1 schema. Scorecards are derived from ball_events + penalties."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _pk() -> Mapped[int]:
    return mapped_column(Integer, primary_key=True, autoincrement=True)


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = _pk()
    player_code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(20), unique=True)
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|suspended|banned
    show_publicly: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")  # name on the public site
    created_at: Mapped[datetime] = _now()


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role", "season_id"),)
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(24))  # super_admin|tournament_admin|umpire|captain|player
    season_id: Mapped[int | None] = mapped_column(ForeignKey("seasons.id"))


class OtpCode(Base):
    __tablename__ = "otp_codes"
    id: Mapped[int] = _pk()
    phone: Mapped[str] = mapped_column(String(20), index=True)
    code_hash: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    refresh_hash: Mapped[str] = mapped_column(String(255), unique=True)
    user_agent: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = _now()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RuleSet(Base):
    __tablename__ = "rule_sets"
    __table_args__ = (UniqueConstraint("name", "version"),)
    id: Mapped[int] = _pk()
    name: Mapped[str] = mapped_column(String(80))
    version: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = _now()


class Season(Base):
    __tablename__ = "seasons"
    id: Mapped[int] = _pk()
    name: Mapped[str] = mapped_column(String(80), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|active|completed|archived
    starts_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rule_set_id: Mapped[int | None] = mapped_column(ForeignKey("rule_sets.id"))
    champion_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    slug: Mapped[str] = mapped_column(String(100), unique=True)  # the season's address on the public site
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    cloned_from_id: Mapped[int | None] = mapped_column(ForeignKey("seasons.id"))


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("season_id", "name"),)
    id: Mapped[int] = _pk()
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"))
    name: Mapped[str] = mapped_column(String(80))
    logo_url: Mapped[str | None] = mapped_column(String(500))
    color: Mapped[str | None] = mapped_column(String(16))
    captain_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    vice_captain_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "user_id"),)
    id: Mapped[int] = _pk()
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|approved|removed


class Stage(Base):
    """A phase of a season: the round robin, then the knockouts."""

    __tablename__ = "stages"
    __table_args__ = (UniqueConstraint("season_id", "ord"),)
    id: Mapped[int] = _pk()
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"))
    kind: Mapped[str] = mapped_column(String(12))  # round_robin|knockout
    name: Mapped[str] = mapped_column(String(60))
    ord: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict] = mapped_column(JSON, default=dict)


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("season_id", "match_no"),)
    id: Mapped[int] = _pk()
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"))
    match_no: Mapped[int] = mapped_column(Integer)
    team_a_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    team_b_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    umpire_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    rule_set_id: Mapped[int] = mapped_column(ForeignKey("rule_sets.id"))
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="scheduled")
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    winner_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    result_text: Mapped[str | None] = mapped_column(String(200))
    seq: Mapped[int] = mapped_column(Integer, default=0)  # bumped on every state change
    stage_id: Mapped[int | None] = mapped_column(ForeignKey("stages.id"))
    round_label: Mapped[str | None] = mapped_column(String(40))  # "Round 3", "Semi-final 1", "Final"
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # null = draft, admins only


class MatchPlayer(Base):
    __tablename__ = "match_players"
    __table_args__ = (UniqueConstraint("match_id", "user_id"),)
    id: Mapped[int] = _pk()
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    batting_order: Mapped[int | None] = mapped_column(Integer)


class Toss(Base):
    __tablename__ = "tosses"
    id: Mapped[int] = _pk()
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), unique=True)
    winner_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    decision: Mapped[str | None] = mapped_column(String(8))  # bat|bowl
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Innings(Base):
    __tablename__ = "innings"
    __table_args__ = (UniqueConstraint("match_id", "number"),)
    id: Mapped[int] = _pk()
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    number: Mapped[int] = mapped_column(Integer)  # 1 or 2
    batting_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    bowling_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    target: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="pending")


class Over(Base):
    __tablename__ = "overs"
    __table_args__ = (UniqueConstraint("innings_id", "number"),)
    id: Mapped[int] = _pk()
    innings_id: Mapped[int] = mapped_column(ForeignKey("innings.id"))
    number: Mapped[int] = mapped_column(Integer)
    over_type: Mapped[str] = mapped_column(String(16))  # normal|bowling_pp|batting_pp
    bowler_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    batter_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    state: Mapped[str] = mapped_column(String(20), default="awaiting_signal")
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DigitSubmission(Base):
    __tablename__ = "digit_submissions"
    __table_args__ = (UniqueConstraint("over_id", "role"),)
    id: Mapped[int] = _pk()
    over_id: Mapped[int] = mapped_column(ForeignKey("overs.id"))
    role: Mapped[str] = mapped_column(String(8))  # bat|bowl
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    digits: Mapped[str] = mapped_column(String(6))
    submitted_at: Mapped[datetime] = _now()
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    overridden_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class BallEvent(Base):
    """Append-only. Corrections insert a higher revision; latest revision wins."""

    __tablename__ = "ball_events"
    __table_args__ = (UniqueConstraint("innings_id", "over_no", "ball_no", "revision"),)
    id: Mapped[int] = _pk()
    innings_id: Mapped[int] = mapped_column(ForeignKey("innings.id"))
    over_no: Mapped[int] = mapped_column(Integer)
    ball_no: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    batter_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    bowler_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    batter_digit: Mapped[int] = mapped_column(Integer)
    bowler_digit: Mapped[int] = mapped_column(Integer)
    runs: Mapped[int] = mapped_column(Integer)
    is_wicket: Mapped[bool] = mapped_column(Boolean)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now()


class Penalty(Base):
    __tablename__ = "penalties"
    __table_args__ = (UniqueConstraint("match_id", "idempotency_key"),)
    id: Mapped[int] = _pk()
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    innings_id: Mapped[int | None] = mapped_column(ForeignKey("innings.id"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    kind: Mapped[str] = mapped_column(String(40))
    runs: Mapped[int] = mapped_column(Integer, default=0)
    wickets: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(64))
    after_over: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # takes effect after this ball
    after_ball: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    applied_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = _pk()
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(60))
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = _now()


class ChatRoom(Base):
    """One per season, plus a match room and an umpire room for each match."""

    __tablename__ = "chat_rooms"
    id: Mapped[int] = _pk()
    kind: Mapped[str] = mapped_column(String(10))  # season|match|umpire
    season_id: Mapped[int | None] = mapped_column(ForeignKey("seasons.id"))
    match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id"))
    scope_key: Mapped[str] = mapped_column(String(32), unique=True)  # e.g. season:3, match:7
    created_at: Mapped[datetime] = _now()


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        UniqueConstraint("room_id", "sender_id", "client_id"),  # retries never duplicate
        Index("ix_chat_messages_room_id_id", "room_id", "id"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("chat_rooms.id"))
    sender_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # null = system
    kind: Mapped[str] = mapped_column(String(12), default="user")  # user|system|announcement
    body: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict | None] = mapped_column(JSON)
    client_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _now()
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reply_to_id: Mapped[int | None] = mapped_column(ForeignKey("chat_messages.id"))
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pinned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class MessageReaction(Base):
    __tablename__ = "message_reactions"
    __table_args__ = (UniqueConstraint("message_id", "user_id", "emoji"),)
    id: Mapped[int] = _pk()
    message_id: Mapped[int] = mapped_column(ForeignKey("chat_messages.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    emoji: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = _now()


class ChatRead(Base):
    """Read receipt as a cursor: the newest message id this user has seen in the room."""

    __tablename__ = "chat_reads"
    __table_args__ = (UniqueConstraint("room_id", "user_id"),)
    id: Mapped[int] = _pk()
    room_id: Mapped[int] = mapped_column(ForeignKey("chat_rooms.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    last_read_id: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = _now()


class MessageReport(Base):
    __tablename__ = "message_reports"
    __table_args__ = (UniqueConstraint("message_id", "reporter_id"),)
    id: Mapped[int] = _pk()
    message_id: Mapped[int] = mapped_column(ForeignKey("chat_messages.id"), index=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="open")  # open|actioned|dismissed
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()


class ChatMute(Base):
    """Blocks posting (not reading) in every room of a season until `until` or `lifted_at`."""

    __tablename__ = "chat_mutes"
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"))
    until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now()
    lifted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "dedupe_key"),  # a retried job never notifies twice
        Index("ix_notifications_user_id_id", "user_id", "id"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict | None] = mapped_column(JSON)
    dedupe_key: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = _now()
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationPref(Base):
    __tablename__ = "notification_prefs"
    __table_args__ = (UniqueConstraint("user_id", "kind"),)
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(24))
    in_app: Mapped[bool] = mapped_column(Boolean)
    push: Mapped[bool | None] = mapped_column(Boolean)  # null = the kind's default for browser push


class MatchResult(Base):
    """The one record the points table reads. Rewritten whenever a result is corrected."""

    __tablename__ = "match_results"
    id: Mapped[int] = _pk()
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), unique=True)
    result_type: Mapped[str] = mapped_column(String(12))  # normal|tie|walkover|abandoned|no_result
    winner_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    # Figures are keyed by the match's own team A and team B. Null for walkovers and abandonments.
    a_runs: Mapped[int | None] = mapped_column(Integer)
    a_balls: Mapped[int | None] = mapped_column(Integer)  # balls team A faced
    a_all_out: Mapped[bool] = mapped_column(Boolean, default=False)
    b_runs: Mapped[int | None] = mapped_column(Integer)
    b_balls: Mapped[int | None] = mapped_column(Integer)
    b_all_out: Mapped[bool] = mapped_column(Boolean, default=False)
    decided_at: Mapped[datetime] = _now()


class PointAdjustment(Base):
    __tablename__ = "point_adjustments"
    id: Mapped[int] = _pk()
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id"))
    points: Mapped[int] = mapped_column(Integer)  # may be negative
    kind: Mapped[str] = mapped_column(String(16))  # umpire_duty|conduct|manual
    reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now()
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MatchDeclaration(Base):
    """A walkover or an abandonment. Kept (not deleted) when reversed, so the history stays visible."""

    __tablename__ = "match_declarations"
    id: Mapped[int] = _pk()
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # walkover|abandoned
    absent_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    reason: Mapped[str] = mapped_column(Text)
    replay_match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id"))
    prev_status: Mapped[str] = mapped_column(String(16))  # what the match was before, to restore on reversal
    declared_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    declared_at: Mapped[datetime] = _now()
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reverse_reason: Mapped[str | None] = mapped_column(Text)


class UmpireDuty(Base):
    """Who was meant to umpire a match, which team supplied them, and whether they turned up."""

    __tablename__ = "umpire_duties"
    __table_args__ = (UniqueConstraint("match_id", "umpire_id"),)
    id: Mapped[int] = _pk()
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    umpire_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))  # the supplying team, if any
    status: Mapped[str] = mapped_column(String(10), default="assigned")  # assigned|performed|missed|replaced
    note: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    adjustment_id: Mapped[int | None] = mapped_column(ForeignKey("point_adjustments.id"))


class MatchAward(Base):
    """Player of the match. One per match and kind; choosing again replaces it."""

    __tablename__ = "match_awards"
    __table_args__ = (UniqueConstraint("match_id", "kind"),)
    id: Mapped[int] = _pk()
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10), default="potm")
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    chosen_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    chosen_at: Mapped[datetime] = _now()


class RosterChange(Base):
    """A captain asks to swap one player for another; an admin decides. Re-checked when approved."""

    __tablename__ = "roster_changes"
    id: Mapped[int] = _pk()
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    out_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    in_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending|approved|rejected|cancelled
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()


class PhoneChangeRequest(Base):
    """A player wants a new number. An admin approves, then the player proves the new number by code."""

    __tablename__ = "phone_change_requests"
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    new_phone: Mapped[str] = mapped_column(String(20), index=True)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending|approved|rejected|completed|cancelled
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PushSubscription(Base):
    """One browser or phone that agreed to receive push notifications for a user."""

    __tablename__ = "push_subscriptions"
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    endpoint: Mapped[str] = mapped_column(String(1000), unique=True)
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(100))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = _now()
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Dispute(Base):
    """A complaint about a match (a result, an eligibility question, the umpiring) or about conduct.

    Never public. Seen by whoever raised it, the captains of the teams involved, and admins who are not
    themselves involved."""

    __tablename__ = "disputes"
    id: Mapped[int] = _pk()
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), index=True)
    match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id"), index=True)
    kind: Mapped[str] = mapped_column(String(12))  # scoring|conduct|eligibility|umpiring|other
    against_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    raised_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    raised_as: Mapped[str] = mapped_column(String(12))  # captain|vice_captain|umpire|player
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="open")  # open|in_review|resolved|dismissed|withdrawn
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    outcome: Mapped[str | None] = mapped_column(Text)
    resolution_ref: Mapped[dict | None] = mapped_column(JSON)  # what was done: {"action": ..., "adjustment_id": ...}
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DisputeMessage(Base):
    __tablename__ = "dispute_messages"
    id: Mapped[int] = _pk()
    dispute_id: Mapped[int] = mapped_column(ForeignKey("disputes.id"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    internal: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")  # admin notes
    created_at: Mapped[datetime] = _now()
