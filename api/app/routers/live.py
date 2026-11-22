"""Read model for a match: header, toss, current over (privacy-filtered) and scorecard."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Match, Over, Penalty, Team, Toss, User
from app.db.session import get_session
from app.deps import get_current_user, is_admin
from app.engine import BAT, BOWL, batting_stats, bowling_stats, summarize_innings
from app.routers.play import digits_of, get_submissions
from app.services.declarations import active_declaration
from app.services.schedule import ensure_visible
from app.services.scoring import engine_inputs, get_innings, load_rules

router = APIRouter(tags=["live"])
REVEALED = ("revealed", "resolved")


async def over_view(db: AsyncSession, over: Over, user: User, official: bool) -> dict:
    """What THIS viewer may see. Opponent and spectators never get digits before the reveal."""
    subs = await get_submissions(db, over.id)
    role = BOWL if user.id == over.bowler_id else BAT if user.id == over.batter_id else None
    out: dict = {
        "number": over.number,
        "over_type": over.over_type,
        "state": over.state,
        "deadline_at": over.deadline_at.isoformat() if over.deadline_at else None,
        "bowler_id": over.bowler_id,
        "batter_id": over.batter_id,
        "submitted": {BAT: BAT in subs, BOWL: BOWL in subs},
        "your_role": role,
        "mine": digits_of(subs.get(role)) if role else None,
        "digits": None,
    }
    if over.state in REVEALED or (official and over.state == "locked"):
        out["digits"] = {BAT: digits_of(subs.get(BAT)), BOWL: digits_of(subs.get(BOWL))}
    return out


@router.get("/matches/{match_id}/live")
async def live(match_id: int, user: User = Depends(get_current_user),
               db: AsyncSession = Depends(get_session)) -> dict:
    m = await db.get(Match, match_id)
    if not m:
        raise HTTPException(404, "Match not found")
    await ensure_visible(db, user, m)
    rules = await load_rules(db, m)
    official = m.umpire_id == user.id or await is_admin(db, user)
    teams = {t.id: t for t in await db.scalars(select(Team).where(Team.id.in_([m.team_a_id, m.team_b_id])))}

    toss = await db.scalar(select(Toss).where(Toss.match_id == m.id))
    inns = await get_innings(db, m.id)
    current: dict | None = None
    cards = []
    loaded = [(inn, *await engine_inputs(db, inn)) for inn in inns]
    ids = {x for _, balls, _ in loaded for b in balls for x in (b.batter_id, b.bowler_id) if x}
    names = {u.id: u.name for u in await db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}
    for inn, balls, pens in loaded:
        s = summarize_innings(balls, pens, rules, inn.target)
        counted = list(s.counted_balls)
        bat = batting_stats(counted)
        bowl = bowling_stats(counted, rules)
        overs: dict[int, list] = {}
        for b in counted:
            overs.setdefault(b.over_no, []).append(
                {"ball": b.ball_no, "batter_digit": b.batter_digit, "bowler_digit": b.bowler_digit,
                 "runs": b.runs, "wicket": b.wicket})
        pen_rows = await db.scalars(select(Penalty).where(Penalty.innings_id == inn.id))
        cards.append({
            "number": inn.number, "status": inn.status, "target": inn.target,
            "batting_team_id": inn.batting_team_id, "bowling_team_id": inn.bowling_team_id,
            "runs": s.runs, "wickets": s.wickets, "overs": s.overs_text,
            "run_rate": s.run_rate, "required_rate": s.required_rate,
            "balls_remaining": s.balls_remaining, "wickets_remaining": s.wickets_remaining,
            "extras": s.penalty_runs, "finish_reason": s.finish_reason,
            "batting": [{"id": x.batter_id, "name": names.get(x.batter_id), "runs": x.runs, "balls": x.balls,
                         "fours": x.fours, "sixes": x.sixes, "out": not x.not_out,
                         "strike_rate": x.strike_rate} for x in bat.values()],
            "bowling": [{"id": x.bowler_id, "name": names.get(x.bowler_id), "overs": x.overs, "runs": x.runs,
                         "wickets": x.wickets, "economy": x.economy} for x in bowl.values()],
            "timeline": [{"over": o, "balls": bs} for o, bs in sorted(overs.items())],
            "penalties": [{"id": p.id, "team_id": p.team_id, "kind": p.kind, "runs": p.runs,
                           "wickets": p.wickets, "reason": p.reason, "voided": p.voided_at is not None}
                          for p in pen_rows],
        })
        if inn.status == "active":
            over = await db.scalar(select(Over).where(Over.innings_id == inn.id)
                                   .order_by(Over.number.desc()).limit(1))
            if over:
                current = await over_view(db, over, user, official)
    decl = await active_declaration(db, m.id)
    return {
        "match": {"id": m.id, "match_no": m.match_no, "status": m.status, "paused": m.paused,
                  "seq": m.seq, "result": m.result_text, "winner_team_id": m.winner_team_id,
                  "umpire_id": m.umpire_id, "overs": rules.overs, "wickets": rules.wickets,
                  "teams": {str(i): t.name for i, t in teams.items()},
                  "team_a_id": m.team_a_id, "team_b_id": m.team_b_id,
                  "declared": {"kind": decl.kind, "reason": decl.reason, "absent_team_id": decl.absent_team_id,
                               "replay_match_id": decl.replay_match_id} if decl else None},
        "you": {"official": official},
        "toss": {"winner_team_id": toss.winner_team_id, "decision": toss.decision} if toss else None,
        "over": current,
        "innings": cards,
    }


