"""Player, team and leaderboard statistics, derived from the ball events on every request.

Nothing is stored: a corrected ball, a changed result or a voided penalty shows up the next time
anyone asks. Only matches whose ledger result is normal or tie count; walkovers and abandoned
matches have no balls to count. Innings are summarised exactly as the scorecard does (same engine, same
counted balls), so player runs always add up to the team total minus penalties.
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    BallEvent,
    Innings,
    Match,
    MatchAward,
    MatchPlayer,
    MatchResult,
    Penalty,
    RuleSet,
    Season,
    User,
)
from app.engine import Ball, RuleConfig, summarize_innings
from app.engine import Penalty as EPenalty
from app.engine.leaderboards import Perf, Totals, aggregate
from app.engine.stats import batting_stats, bowling_stats
from app.services.results import season_config

COUNTED = ("normal", "tie")


@dataclass
class Loaded:
    matches: dict[int, Match] = field(default_factory=dict)
    perfs: list[Perf] = field(default_factory=list)
    innings_runs: dict[tuple[int, int], tuple[int, int]] = field(default_factory=dict)  # (match, n) -> (ball runs, penalty runs)
    awards: dict[int, int] = field(default_factory=dict)  # match_id -> user_id


async def load(db: AsyncSession, *, season_id: int | None = None, user_id: int | None = None,
               team_id: int | None = None, match_id: int | None = None) -> Loaded:
    """Per-match performances for every counted match in scope (filters combine)."""
    q = (select(Match).join(MatchResult, MatchResult.match_id == Match.id)
         .where(MatchResult.result_type.in_(COUNTED)).order_by(Match.id))
    if season_id is not None:
        q = q.where(Match.season_id == season_id)
    if match_id is not None:
        q = q.where(Match.id == match_id)
    if user_id is not None:
        q = q.where(Match.id.in_(select(MatchPlayer.match_id).where(MatchPlayer.user_id == user_id)))
    if team_id is not None:
        q = q.where((Match.team_a_id == team_id) | (Match.team_b_id == team_id))
    out = Loaded(matches={m.id: m for m in await db.scalars(q)})
    if not out.matches:
        return out
    ids = list(out.matches)
    inns_by_match: dict[int, list[Innings]] = {}
    for i in await db.scalars(select(Innings).where(Innings.match_id.in_(ids)).order_by(Innings.number)):
        inns_by_match.setdefault(i.match_id, []).append(i)
    inn_ids = [i.id for lst in inns_by_match.values() for i in lst]
    balls: dict[int, list[Ball]] = {}
    for e in await db.scalars(select(BallEvent).where(BallEvent.innings_id.in_(inn_ids))):
        balls.setdefault(e.innings_id, []).append(Ball(e.over_no, e.ball_no, e.batter_digit, e.bowler_digit, e.runs,
                                                       e.is_wicket, e.batter_id, e.bowler_id, e.revision))
    pens: dict[int, list[EPenalty]] = {}
    for pen in await db.scalars(select(Penalty).where(Penalty.innings_id.in_(inn_ids))):
        pens.setdefault(pen.innings_id or 0, []).append(
            EPenalty(pen.runs, pen.wickets, pen.after_over, pen.after_ball, pen.voided_at is not None, pen.reason))
    rule_ids = {m.rule_set_id for m in out.matches.values()}
    rules = {rs.id: RuleConfig.from_dict(rs.config) for rs in await db.scalars(select(RuleSet).where(RuleSet.id.in_(rule_ids)))}
    lineup: dict[int, dict[int, int]] = {}
    for mp in await db.scalars(select(MatchPlayer).where(MatchPlayer.match_id.in_(ids))):
        lineup.setdefault(mp.match_id, {})[mp.user_id] = mp.team_id
    for a in await db.scalars(select(MatchAward).where(MatchAward.match_id.in_(ids), MatchAward.kind == "potm")):
        out.awards[a.match_id] = a.user_id

    for mid, m in out.matches.items():
        cfg = rules.get(m.rule_set_id, RuleConfig())
        when = int(m.scheduled_at.timestamp()) if m.scheduled_at else 0
        per: dict[int, Perf] = {u: Perf(mid, u, t, when) for u, t in lineup.get(mid, {}).items()}

        for inn in inns_by_match.get(mid, []):
            s = summarize_innings(balls.get(inn.id, []), pens.get(inn.id, []), cfg, inn.target)
            out.innings_runs[(mid, inn.number)] = (s.ball_runs, s.penalty_runs)
            for uid, b in batting_stats(s.counted_balls).items():
                p = per.setdefault(uid, Perf(mid, uid, inn.batting_team_id, when))
                p.batted, p.runs, p.balls, p.fours, p.sixes, p.outs = True, b.runs, b.balls, b.fours, b.sixes, b.dismissals
            for uid, w in bowling_stats(s.counted_balls, cfg).items():
                p = per.setdefault(uid, Perf(mid, uid, inn.bowling_team_id, when))
                p.bowled, p.bowl_balls, p.bowl_runs, p.wickets = True, w.balls, w.runs, w.wickets
        out.perfs.extend(per.values())
    return out


def filter_team(perfs: list[Perf], team_id: int | None) -> list[Perf]:
    return [p for p in perfs if team_id is None or p.team_id == team_id]


async def totals_for(db: AsyncSession, **scope: int | None) -> tuple[dict[int, Totals], Loaded]:
    team_id = scope.pop("team_id", None)
    data = await load(db, team_id=team_id, **scope)
    perfs = filter_team(data.perfs, team_id)
    counts: dict[int, int] = {}
    for mid, uid in data.awards.items():
        if any(p.match_id == mid and p.user_id == uid and (team_id is None or p.team_id == team_id) for p in perfs):
            counts[uid] = counts.get(uid, 0) + 1
    return aggregate(perfs, counts), data


async def thresholds(db: AsyncSession, season: Season) -> tuple[int, int, int]:
    cfg = await season_config(db, season)
    s = {"min_balls_strike_rate": 12, "min_balls_economy": 12, **(cfg.get("stats") or {})}
    return int(s["min_balls_strike_rate"]), int(s["min_balls_economy"]), RuleConfig.from_dict(cfg).balls_per_over


async def user_names(db: AsyncSession, ids: set[int]) -> dict[int, User]:
    if not ids:
        return {}
    return {u.id: u for u in await db.scalars(select(User).where(User.id.in_(ids)))}
