"""Match flow: toss, overs, private digit submission, resolution, penalties, corrections."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AuditLog,
    BallEvent,
    DigitSubmission,
    Innings,
    Match,
    MatchPlayer,
    Over,
    Penalty,
    Team,
    Toss,
    User,
)
from app.db.session import get_session
from app.deps import get_current_user, is_admin
from app.engine import BAT, BOWL, RuleConfig, parse_digits, play_over, validate_submission
from app.realtime import publish_change
from app.routers.teams import can_manage
from app.services import match_events as events
from app.services.outbox import flush as flush_outbox
from app.services.scoring import Recomputed, engine_inputs, get_innings, load_rules, recompute

router = APIRouter(tags=["play"])


# ---------- helpers ----------
async def lock_match(db: AsyncSession, match_id: int) -> Match:
    m = await db.scalar(select(Match).where(Match.id == match_id).with_for_update())
    if not m:
        raise HTTPException(404, "Match not found")
    return m


async def ensure_official(db: AsyncSession, user: User, m: Match) -> None:
    if m.umpire_id != user.id and not await is_admin(db, user):
        raise HTTPException(403, "Only the match umpire or an admin can do this")


def ensure_running(m: Match) -> None:
    if m.paused:
        raise HTTPException(409, "Match is paused")


def audit(db: AsyncSession, actor: User, action: str, entity: str, entity_id: int | None,
          reason: str | None = None, before: dict | None = None, after: dict | None = None) -> None:
    db.add(AuditLog(actor_id=actor.id, action=action, entity=entity, entity_id=entity_id,
                    reason=reason, before=before, after=after))


async def commit_match(db: AsyncSession, m: Match) -> None:
    """Bump the sequence number, commit, then tell watchers (after the commit succeeds)."""
    m.seq += 1
    match_id, seq = m.id, m.seq
    await db.commit()
    await publish_change(match_id, seq)
    await flush_outbox(db)  # announcements and notifications go out only after the commit


async def active_innings(db: AsyncSession, m: Match) -> Innings:
    for i in await get_innings(db, m.id):
        if i.status == "active":
            return i
    raise HTTPException(409, "No innings in progress")


async def current_over(db: AsyncSession, innings: Innings) -> Over | None:
    return await db.scalar(
        select(Over).where(Over.innings_id == innings.id).order_by(Over.number.desc()).limit(1)
    )


async def lineup_ids(db: AsyncSession, match_id: int, team_id: int) -> set[int]:
    rows = await db.scalars(
        select(MatchPlayer.user_id).where(MatchPlayer.match_id == match_id, MatchPlayer.team_id == team_id)
    )
    return set(rows)


async def get_submissions(db: AsyncSession, over_id: int) -> dict[str, DigitSubmission]:
    rows = await db.scalars(select(DigitSubmission).where(DigitSubmission.over_id == over_id))
    return {s.role: s for s in rows}


def digits_of(sub: DigitSubmission | None) -> list[int] | None:
    return [int(c) for c in sub.digits] if sub else None


# ---------- toss ----------
class WinnerIn(BaseModel):
    winner_team_id: int


class DecisionIn(BaseModel):
    decision: str = Field(pattern=r"^(bat|bowl)$")


@router.post("/matches/{match_id}/toss/open", status_code=204)
async def toss_open(match_id: int, user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_session)) -> None:
    m = await lock_match(db, match_id)
    await ensure_official(db, user, m)
    if m.status != "scheduled":
        raise HTTPException(409, "Toss can only be opened for a scheduled match")
    for t in (m.team_a_id, m.team_b_id):
        if not await lineup_ids(db, m.id, t):
            raise HTTPException(409, "Both teams need a lineup before the toss")
    db.add(Toss(match_id=m.id))
    m.status = "toss"
    await events.toss_opened(db, m)
    await commit_match(db, m)


@router.post("/matches/{match_id}/toss/winner", status_code=204)
async def toss_winner(match_id: int, body: WinnerIn, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_session)) -> None:
    m = await lock_match(db, match_id)
    await ensure_official(db, user, m)
    if m.status != "toss":
        raise HTTPException(409, "Toss is not open")
    if body.winner_team_id not in (m.team_a_id, m.team_b_id):
        raise HTTPException(400, "Winner must be one of the two teams")
    toss = await db.scalar(select(Toss).where(Toss.match_id == m.id))
    assert toss is not None
    toss.winner_team_id, toss.decision, toss.decided_at = body.winner_team_id, None, None
    await commit_match(db, m)


@router.post("/matches/{match_id}/toss/decision", status_code=204)
async def toss_decision(match_id: int, body: DecisionIn, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_session)) -> None:
    m = await lock_match(db, match_id)
    toss = await db.scalar(select(Toss).where(Toss.match_id == m.id))
    if m.status != "toss" or not toss or not toss.winner_team_id:
        raise HTTPException(409, "Toss winner not decided yet")
    team = await db.get(Team, toss.winner_team_id)
    assert team is not None
    if not (m.umpire_id == user.id or await can_manage(db, user, team)):
        raise HTTPException(403, "Only the winning captain, umpire or admin can choose")
    toss.decision, toss.decided_at = body.decision, datetime.now(UTC)
    await commit_match(db, m)


@router.post("/matches/{match_id}/toss/confirm", status_code=204)
async def toss_confirm(match_id: int, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_session)) -> None:
    m = await lock_match(db, match_id)
    await ensure_official(db, user, m)
    toss = await db.scalar(select(Toss).where(Toss.match_id == m.id))
    if m.status != "toss" or not toss or not toss.winner_team_id or not toss.decision:
        raise HTTPException(409, "Toss needs a winner and a decision first")
    other = m.team_b_id if toss.winner_team_id == m.team_a_id else m.team_a_id
    first_bat, first_bowl = (
        (toss.winner_team_id, other) if toss.decision == "bat" else (other, toss.winner_team_id)
    )
    db.add(Innings(match_id=m.id, number=1, batting_team_id=first_bat, bowling_team_id=first_bowl))
    db.add(Innings(match_id=m.id, number=2, batting_team_id=first_bowl, bowling_team_id=first_bat))
    toss.confirmed_by = user.id
    m.status = "ready"
    audit(db, user, "toss.confirm", "match", m.id, after={"winner": toss.winner_team_id, "decision": toss.decision})
    await events.toss_confirmed(db, m, toss.winner_team_id, toss.decision)
    await commit_match(db, m)


# ---------- match control ----------
@router.post("/matches/{match_id}/start", status_code=204)
async def start_match(match_id: int, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_session)) -> None:
    m = await lock_match(db, match_id)
    await ensure_official(db, user, m)
    if m.status != "ready":
        raise HTTPException(409, "Match is not ready to start")
    inns = await get_innings(db, m.id)
    inns[0].status = "active"
    m.status = "innings1"
    await events.innings_started(db, m, inns[0])
    await commit_match(db, m)


@router.post("/matches/{match_id}/innings/next", status_code=204)
async def next_innings(match_id: int, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_session)) -> None:
    m = await lock_match(db, match_id)
    await ensure_official(db, user, m)
    ensure_running(m)
    if m.status != "break":
        raise HTTPException(409, "Not in the innings break")
    inns = await get_innings(db, m.id)
    inns[1].status = "active"
    m.status = "innings2"
    await events.innings_started(db, m, inns[1])
    await commit_match(db, m)


async def _set_paused(db: AsyncSession, match_id: int, user: User, paused: bool) -> None:
    m = await lock_match(db, match_id)
    await ensure_official(db, user, m)
    if m.status not in ("innings1", "break", "innings2"):
        raise HTTPException(409, "Only a live match can be paused")
    m.paused = paused
    audit(db, user, "match.pause" if paused else "match.resume", "match", m.id)
    await events.paused(db, m, paused)
    await commit_match(db, m)


@router.post("/matches/{match_id}/pause", status_code=204)
async def pause(match_id: int, user: User = Depends(get_current_user),
                db: AsyncSession = Depends(get_session)) -> None:
    await _set_paused(db, match_id, user, True)


@router.post("/matches/{match_id}/resume", status_code=204)
async def resume(match_id: int, user: User = Depends(get_current_user),
                 db: AsyncSession = Depends(get_session)) -> None:
    await _set_paused(db, match_id, user, False)


# ---------- overs ----------
class OverStartIn(BaseModel):
    bowler_id: int
    batter_id: int


@router.post("/matches/{match_id}/overs/start", status_code=201)
async def over_start(match_id: int, body: OverStartIn, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_session)) -> dict:
    m = await lock_match(db, match_id)
    await ensure_official(db, user, m)
    ensure_running(m)
    rules = await load_rules(db, m)
    inn = await active_innings(db, m)
    last = await current_over(db, inn)
    if last and last.state != "resolved":
        raise HTTPException(409, f"Over {last.number} is still in progress")
    number = (last.number if last else 0) + 1
    if number > rules.overs:
        raise HTTPException(409, "All overs have been bowled")
    if body.bowler_id not in await lineup_ids(db, m.id, inn.bowling_team_id):
        raise HTTPException(400, "Bowler must be in the bowling team's lineup")
    if body.batter_id not in await lineup_ids(db, m.id, inn.batting_team_id):
        raise HTTPException(400, "Batter must be in the batting team's lineup")
    bowled = await db.scalar(
        select(func.count()).select_from(Over).where(Over.innings_id == inn.id, Over.bowler_id == body.bowler_id)
    )
    if (bowled or 0) >= rules.max_overs_per_bowler:
        raise HTTPException(409, f"Bowler has already bowled {rules.max_overs_per_bowler} overs")
    over = Over(innings_id=inn.id, number=number, over_type=rules.over_type(number),
                bowler_id=body.bowler_id, batter_id=body.batter_id)
    db.add(over)
    await commit_match(db, m)
    return {"number": number, "over_type": over.over_type, "state": over.state}


async def _current(db: AsyncSession, m: Match) -> tuple[Innings, Over]:
    inn = await active_innings(db, m)
    over = await current_over(db, inn)
    if not over or over.state == "resolved":
        raise HTTPException(409, "No over in progress")
    return inn, over


@router.post("/matches/{match_id}/overs/current/signal", status_code=204)
async def over_signal(match_id: int, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_session)) -> None:
    m = await lock_match(db, match_id)
    await ensure_official(db, user, m)
    ensure_running(m)
    rules = await load_rules(db, m)
    inn, over = await _current(db, m)
    if over.state != "awaiting_signal":
        raise HTTPException(409, "Signal already sent")
    over.state = "submissions_open"
    over.deadline_at = datetime.now(UTC) + timedelta(seconds=rules.submission_seconds)
    await events.over_signalled(db, m, inn, over)
    await commit_match(db, m)


class SubmitIn(BaseModel):
    digits: str | list[int]


async def _store(db: AsyncSession, over: Over, role: str, user_id: int, digits: list[int],
                 *, by: int | None = None) -> DigitSubmission:
    text = "".join(map(str, digits))
    sub = DigitSubmission(over_id=over.id, role=role, user_id=user_id, digits=text,
                          locked_at=datetime.now(UTC), overridden_by=by)
    db.add(sub)
    return sub


def _validated(raw: str | list[int], role: str, over: Over, rules: RuleConfig) -> list[int]:
    digits = parse_digits(raw)
    if digits is None:
        raise HTTPException(422, {"errors": [{"code": "invalid_digit", "message": "Digits only, 1-6"}]})
    bad = validate_submission(role, digits, over.number, rules)
    if bad:
        raise HTTPException(422, {"errors": [{"code": v.code, "message": v.message} for v in bad]})
    return digits


@router.post("/matches/{match_id}/overs/current/submit")
async def submit_digits(match_id: int, body: SubmitIn, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_session)) -> dict:
    m = await lock_match(db, match_id)
    ensure_running(m)
    rules = await load_rules(db, m)
    _, over = await _current(db, m)
    if user.id == over.bowler_id:
        role = BOWL
    elif user.id == over.batter_id:
        role = BAT
    else:
        raise HTTPException(403, "You are not the batter or bowler for this over")
    if not user.phone_verified:
        raise HTTPException(403, "Verify your registered mobile number to play")
    if over.state != "submissions_open":
        raise HTTPException(409, "Submissions are not open")
    if over.deadline_at and datetime.now(UTC) > over.deadline_at:
        raise HTTPException(409, "Submission deadline has passed; ask the umpire")
    digits = _validated(body.digits, role, over, rules)
    existing = (await get_submissions(db, over.id)).get(role)
    if existing:
        if existing.digits == "".join(map(str, digits)):
            return {"status": "already_submitted", "role": role}  # idempotent retry
        raise HTTPException(409, "You already submitted and locked your digits")
    await _store(db, over, role, user.id, digits)
    try:
        await commit_match(db, m)
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(409, "Duplicate submission") from e
    return {"status": "submitted", "role": role}


class OverrideIn(BaseModel):
    role: str = Field(pattern=r"^(bat|bowl)$")
    digits: str | list[int]
    reason: str = Field(min_length=3)


@router.post("/matches/{match_id}/overs/current/override", status_code=204)
async def override_digits(match_id: int, body: OverrideIn, user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_session)) -> None:
    m = await lock_match(db, match_id)
    await ensure_official(db, user, m)
    rules = await load_rules(db, m)
    _, over = await _current(db, m)
    if over.state not in ("submissions_open", "locked"):
        raise HTTPException(409, "Digits can only be overridden before the reveal")
    digits = _validated(body.digits, body.role, over, rules)
    owner = over.bowler_id if body.role == BOWL else over.batter_id
    assert owner is not None
    existing = (await get_submissions(db, over.id)).get(body.role)
    before = {"digits": existing.digits} if existing else None
    if existing:
        existing.digits, existing.overridden_by = "".join(map(str, digits)), user.id
        existing.locked_at = datetime.now(UTC)
    else:
        await _store(db, over, body.role, owner, digits, by=user.id)
    audit(db, user, "digits.override", "over", over.id, body.reason, before, {"role": body.role})
    await events.digits_overridden(db, m, over, body.role, user.name, body.reason)
    await commit_match(db, m)


@router.post("/matches/{match_id}/overs/current/lock", status_code=204)
async def over_lock(match_id: int, user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_session)) -> None:
    m = await lock_match(db, match_id)
    await ensure_official(db, user, m)
    ensure_running(m)
    _, over = await _current(db, m)
    if over.state != "submissions_open":
        raise HTTPException(409, "Submissions are not open")
    subs = await get_submissions(db, over.id)
    missing = [r for r in (BAT, BOWL) if r not in subs]
    if missing:
        raise HTTPException(409, f"Still waiting for: {', '.join(missing)} (use override if absent)")
    over.state = "locked"
    await events.over_locked(db, m)
    await commit_match(db, m)


@router.post("/matches/{match_id}/overs/current/reveal", status_code=204)
async def over_reveal(match_id: int, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_session)) -> None:
    m = await lock_match(db, match_id)
    await ensure_official(db, user, m)
    ensure_running(m)
    _, over = await _current(db, m)
    if over.state != "locked":
        raise HTTPException(409, "Lock the submissions first")
    over.state = "revealed"
    await commit_match(db, m)


@router.post("/matches/{match_id}/overs/current/resolve")
async def over_resolve(match_id: int, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_session)) -> dict:
    m = await lock_match(db, match_id)  # row lock: a second resolve waits, then sees 'resolved'
    await ensure_official(db, user, m)
    ensure_running(m)
    rules = await load_rules(db, m)
    inn, over = await _current(db, m)
    if over.state != "revealed":
        raise HTTPException(409, "Reveal the digits first")
    subs = await get_submissions(db, over.id)
    bat, bowl = digits_of(subs[BAT]), digits_of(subs[BOWL])
    assert bat is not None and bowl is not None
    balls, pens = await engine_inputs(db, inn)
    new, _ = play_over(balls, pens, over.number, bat, bowl, rules, inn.target,
                       over.batter_id, over.bowler_id)
    for b in new:
        db.add(BallEvent(innings_id=inn.id, over_no=b.over_no, ball_no=b.ball_no, revision=1,
                         batter_id=b.batter_id, bowler_id=b.bowler_id, batter_digit=b.batter_digit,
                         bowler_digit=b.bowler_digit, runs=b.runs, is_wicket=b.wicket, created_by=user.id))
    over.state = "resolved"
    await db.flush()
    prev_status, prev_result = m.status, m.result_text
    rec = await recompute(db, m, rules)
    await events.over_resolved(db, m, inn, over, new, rec, prev_status, prev_result, rules)
    await commit_match(db, m)
    return {"balls": len(new), "match_status": m.status, "result": m.result_text}


# ---------- penalties ----------
class PenaltyIn(BaseModel):
    team_id: int  # the team whose innings total is adjusted
    kind: str = Field(min_length=2, max_length=40)
    runs: int = 0
    wickets: int = Field(default=0, ge=0)
    reason: str = Field(min_length=3)
    idempotency_key: str = Field(min_length=4, max_length=64)


async def _innings_of_team(db: AsyncSession, m: Match, team_id: int) -> Innings:
    for i in await get_innings(db, m.id):
        if i.batting_team_id == team_id and i.status != "pending":
            return i
    raise HTTPException(409, "That team has no innings in progress or completed")


@router.post("/matches/{match_id}/penalties", status_code=201)
async def add_penalty(match_id: int, body: PenaltyIn, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_session)) -> dict:
    m = await lock_match(db, match_id)
    await ensure_official(db, user, m)
    if body.runs == 0 and body.wickets == 0:
        raise HTTPException(400, "A penalty needs runs or wickets")
    dup = await db.scalar(select(Penalty).where(Penalty.match_id == m.id,
                                                Penalty.idempotency_key == body.idempotency_key))
    if dup:  # same request retried: never apply twice
        return {"id": dup.id, "duplicate": True}
    rules = await load_rules(db, m)
    inn = await _innings_of_team(db, m, body.team_id)
    balls, _ = await engine_inputs(db, inn)
    last = max(((b.over_no, b.ball_no) for b in balls), default=(0, 0))
    pen = Penalty(match_id=m.id, innings_id=inn.id, team_id=body.team_id, kind=body.kind,
                  runs=body.runs, wickets=body.wickets, reason=body.reason,
                  idempotency_key=body.idempotency_key, applied_by=user.id,
                  after_over=last[0], after_ball=last[1])
    db.add(pen)
    try:
        await db.flush()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(409, "Duplicate penalty") from e
    audit(db, user, "penalty.apply", "penalty", pen.id, body.reason,
          after={"team": body.team_id, "runs": body.runs, "wickets": body.wickets})
    prev_status, prev_result = m.status, m.result_text
    rec = await recompute(db, m, rules)
    await events.penalty_applied(db, m, pen, user.name)
    await events.status_changed(db, m, rec, prev_status, prev_result)
    await commit_match(db, m)
    return {"id": pen.id, "duplicate": False, "match_status": m.status}


class VoidIn(BaseModel):
    reason: str = Field(min_length=3)


@router.post("/matches/{match_id}/penalties/{penalty_id}/void", status_code=204)
async def void_penalty(match_id: int, penalty_id: int, body: VoidIn,
                       user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_session)) -> None:
    m = await lock_match(db, match_id)
    await ensure_official(db, user, m)
    pen = await db.get(Penalty, penalty_id)
    if not pen or pen.match_id != m.id:
        raise HTTPException(404, "Penalty not found")
    if pen.voided_at:
        return
    rules = await load_rules(db, m)
    pen.voided_at = datetime.now(UTC)
    audit(db, user, "penalty.void", "penalty", pen.id, body.reason)
    await db.flush()
    prev_status, prev_result = m.status, m.result_text
    rec = await _guard_and_recompute(db, m, rules)
    await events.penalty_voided(db, m, pen, user.name, body.reason)
    await events.status_changed(db, m, rec, prev_status, prev_result)
    await commit_match(db, m)


# ---------- corrections ----------
class CorrectIn(BaseModel):
    innings_number: int = Field(ge=1, le=2)
    over_no: int = Field(ge=1)
    ball_no: int = Field(ge=1, le=6)
    batter_digit: int = Field(ge=1, le=6)
    bowler_digit: int = Field(ge=1, le=6)
    reason: str = Field(min_length=3)


async def _guard_and_recompute(db: AsyncSession, m: Match, rules: RuleConfig) -> Recomputed | None:
    """Recompute, refusing a change that would reopen innings 1 after innings 2 began."""
    inns = await get_innings(db, m.id)
    was_finished = inns[0].status == "completed"
    b2, _ = await engine_inputs(db, inns[1])
    rec = await recompute(db, m, rules)
    if was_finished and inns[0].status != "completed" and b2:
        await db.rollback()
        raise HTTPException(409, "This change would reopen innings 1 after innings 2 started")
    return rec


@router.post("/matches/{match_id}/balls/correct", status_code=201)
async def correct_ball(match_id: int, body: CorrectIn, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_session)) -> dict:
    m = await lock_match(db, match_id)
    await ensure_official(db, user, m)
    rules = await load_rules(db, m)
    inns = await get_innings(db, m.id)
    inn = inns[body.innings_number - 1]
    if inn.status == "pending":
        raise HTTPException(409, "That innings has not started")
    latest = await db.scalar(
        select(BallEvent).where(BallEvent.innings_id == inn.id, BallEvent.over_no == body.over_no,
                                BallEvent.ball_no == body.ball_no).order_by(BallEvent.revision.desc()).limit(1))
    if not latest:
        raise HTTPException(404, "No such ball was recorded")
    wicket = rules.same_digit_is_wicket and body.batter_digit == body.bowler_digit
    ev = BallEvent(innings_id=inn.id, over_no=body.over_no, ball_no=body.ball_no,
                   revision=latest.revision + 1, batter_id=latest.batter_id, bowler_id=latest.bowler_id,
                   batter_digit=body.batter_digit, bowler_digit=body.bowler_digit,
                   runs=0 if wicket else body.batter_digit, is_wicket=wicket, created_by=user.id)
    db.add(ev)
    audit(db, user, "ball.correct", "ball_event", latest.id, body.reason,
          {"batter": latest.batter_digit, "bowler": latest.bowler_digit, "runs": latest.runs},
          {"batter": ev.batter_digit, "bowler": ev.bowler_digit, "runs": ev.runs})
    await db.flush()
    prev_status, prev_result = m.status, m.result_text
    rec = await _guard_and_recompute(db, m, rules)
    await events.ball_corrected(db, m, body.innings_number, body.over_no, body.ball_no,
                                {"runs": latest.runs, "wicket": latest.is_wicket}, {"runs": ev.runs, "wicket": ev.is_wicket},
                                user.name, body.reason)
    await events.status_changed(db, m, rec, prev_status, prev_result)
    await commit_match(db, m)
    return {"revision": ev.revision, "match_status": m.status, "result": m.result_text}
