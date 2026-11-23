"""The live read model of a match: header, toss, current over (privacy-filtered) and scorecard.

One builder serves signed-in viewers and the public, so hidden digits stay hidden by the same code.
`viewer=None` is an anonymous visitor: no "your" data, no unrevealed digits, names as the public
may see them, and no free-text reasons.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Match, MatchAward, Over, Penalty, Team, Toss, User
from app.deps import is_admin
from app.engine import BAT, BOWL, batting_stats, bowling_stats, summarize_innings
from app.routers.play import digits_of, get_submissions
from app.services.declarations import active_declaration, toss_absent_from
from app.services.public import name_of, people
from app.services.scoring import engine_inputs, get_innings, load_rules

REVEALED = ("revealed", "resolved")


async def over_view(db: AsyncSession, over: Over, viewer: User | None, official: bool) -> dict:
    """What THIS viewer may see. Opponent and spectators never get digits before the reveal."""
    subs = await get_submissions(db, over.id)
    uid = viewer.id if viewer else None
    role = BOWL if uid is not None and uid == over.bowler_id else BAT if uid is not None and uid == over.batter_id else None
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


async def build_live(db: AsyncSession, m: Match, viewer: User | None) -> dict:
    public = viewer is None
    rules = await load_rules(db, m)
    official = viewer is not None and (m.umpire_id == viewer.id or await is_admin(db, viewer, m.season_id))
    teams = {t.id: t for t in await db.scalars(select(Team).where(Team.id.in_([m.team_a_id, m.team_b_id])))}

    toss = await db.scalar(select(Toss).where(Toss.match_id == m.id))
    inns = await get_innings(db, m.id)
    current: dict | None = None
    cards = []
    loaded = [(inn, *await engine_inputs(db, inn)) for inn in inns]
    potm = await db.scalar(select(User).join(MatchAward, MatchAward.user_id == User.id)
                           .where(MatchAward.match_id == m.id, MatchAward.kind == "potm"))
    ids = {x for _, balls, _ in loaded for b in balls for x in (b.batter_id, b.bowler_id) if x}
    ids |= {potm.id} if potm else set()
    users = {u.id: u for u in await db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}
    known = await people(db, ids | {i for i in (m.umpire_id,) if i}) if public else {}

    def who(uid: int | None) -> tuple[int | None, str | None]:
        """(id, name) as this viewer may see them."""
        if uid is None:
            return None, None
        if public:
            p = known.get(uid)
            return (p["id"], p["name"]) if p else (None, None)
        u = users.get(uid)
        return uid, u.name if u else None

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
            "batting": [{"id": who(x.batter_id)[0], "name": who(x.batter_id)[1], "runs": x.runs, "balls": x.balls,
                         "fours": x.fours, "sixes": x.sixes, "out": not x.not_out,
                         "strike_rate": x.strike_rate} for x in bat.values() if not public or who(x.batter_id)[1]],
            "bowling": [{"id": who(x.bowler_id)[0], "name": who(x.bowler_id)[1], "overs": x.overs, "runs": x.runs,
                         "wickets": x.wickets, "economy": x.economy} for x in bowl.values() if not public or who(x.bowler_id)[1]],
            "timeline": [{"over": o, "balls": bs} for o, bs in sorted(overs.items())],
            "penalties": [{"id": p.id, "team_id": p.team_id, "kind": p.kind, "runs": p.runs,
                           "wickets": p.wickets, "reason": None if public else p.reason, "voided": p.voided_at is not None}
                          for p in pen_rows],
        })
        if inn.status == "active":
            over = await db.scalar(select(Over).where(Over.innings_id == inn.id)
                                   .order_by(Over.number.desc()).limit(1))
            if over:
                current = await over_view(db, over, viewer, official)
                if public:  # spectators see who is up, by public name, and nothing about "you"
                    current.pop("mine", None)
                    current["bowler_id"], current["batter_id"] = None, None
                    up = await people(db, {i for i in (over.bowler_id, over.batter_id) if i})
                    current["bowler"], current["batter"] = name_of(up, over.bowler_id), name_of(up, over.batter_id)
    decl = await active_declaration(db, m.id)
    result = m.result_text
    if public and decl and decl.kind == "abandoned":
        result = "Match abandoned"  # the free-text reason stays inside the league
    absent_from = await toss_absent_from(db, m) if official else None
    potm_id, potm_name = who(potm.id if potm else None)
    potm_out = {"id": potm_id, "name": potm_name} if potm_name else None
    return {
        "match": {"id": m.id, "match_no": m.match_no, "status": m.status, "paused": m.paused,
                  "seq": m.seq, "result": result, "winner_team_id": m.winner_team_id,
                  "umpire_id": None if public else m.umpire_id, "overs": rules.overs, "wickets": rules.wickets,
                  "teams": {str(i): t.name for i, t in teams.items()},
                  "potm": potm_out,
                  "team_a_id": m.team_a_id, "team_b_id": m.team_b_id,
                  "declared": {"kind": decl.kind, "reason": None if public else decl.reason,
                               "absent_team_id": decl.absent_team_id,
                               "replay_match_id": None if public else decl.replay_match_id} if decl else None},
        "you": {"official": official, "toss_absent_from": absent_from.isoformat() if absent_from else None},
        "toss": {"winner_team_id": toss.winner_team_id, "decision": toss.decision} if toss else None,
        "over": current,
        "innings": cards,
    }


__all__ = ["build_live", "name_of", "over_view"]
