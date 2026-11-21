"""DB-aware glue between the pure engine and the stored events.

recompute() is the single place that derives innings/match state from ball
events and penalties, so resolve, penalty and correction all agree.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BallEvent, Innings, Match, Penalty, RuleSet, Team
from app.engine import Ball, InningsSummary, RuleConfig, decide_match, summarize_innings
from app.engine import Penalty as EPenalty


async def load_rules(db: AsyncSession, match: Match) -> RuleConfig:
    rs = await db.get(RuleSet, match.rule_set_id)
    return RuleConfig.from_dict(rs.config if rs else None)


async def get_innings(db: AsyncSession, match_id: int) -> list[Innings]:
    rows = await db.scalars(select(Innings).where(Innings.match_id == match_id).order_by(Innings.number))
    return list(rows)


async def engine_inputs(db: AsyncSession, innings: Innings) -> tuple[list[Ball], list[EPenalty]]:
    rows = await db.scalars(select(BallEvent).where(BallEvent.innings_id == innings.id))
    balls = [
        Ball(
            e.over_no, e.ball_no, e.batter_digit, e.bowler_digit, e.runs, e.is_wicket,
            e.batter_id, e.bowler_id, e.revision,
        )
        for e in rows
    ]
    pens = await db.scalars(select(Penalty).where(Penalty.innings_id == innings.id))
    epens = [
        EPenalty(p.runs, p.wickets, p.after_over, p.after_ball, p.voided_at is not None, p.reason)
        for p in pens
    ]
    return balls, epens


@dataclass
class Recomputed:
    first: InningsSummary
    second: InningsSummary | None
    result_text: str | None


async def recompute(db: AsyncSession, match: Match, rules: RuleConfig) -> Recomputed | None:
    """Re-derive innings status, target and match result. Caller commits."""
    inns = await get_innings(db, match.id)
    if len(inns) < 2:
        return None
    i1, i2 = inns
    b1, p1 = await engine_inputs(db, i1)
    s1 = summarize_innings(b1, p1, rules)
    if i1.status != "pending":
        i1.status = "completed" if s1.finished else "active"
    i2.target = s1.runs + 1 if s1.finished else None
    if match.status == "innings1" and s1.finished:
        match.status = "break"
    if not i2.target or i2.status == "pending":
        return Recomputed(s1, None, None)

    b2, p2 = await engine_inputs(db, i2)
    s2 = summarize_innings(b2, p2, rules, i2.target)
    i2.status = "completed" if s2.finished else "active"
    text = None
    if s2.finished:
        res = decide_match(s1, s2, rules)
        names = {t.id: t.name for t in await db.scalars(select(Team).where(Team.id.in_([i1.batting_team_id, i2.batting_team_id])))}
        winner_id = None
        if res.winner == "first":
            winner_id = i1.batting_team_id
        elif res.winner == "second":
            winner_id = i2.batting_team_id
        text = res.text if winner_id is None else f"{names[winner_id]} {res.text}"
        match.status, match.winner_team_id, match.result_text = "completed", winner_id, text
    elif match.status == "completed":
        match.status, match.winner_team_id, match.result_text = "innings2", None, None
    return Recomputed(s1, s2, text)
