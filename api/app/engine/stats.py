"""Individual statistics. Computed from ball events only, so penalties never leak in."""

from collections.abc import Iterable
from dataclasses import dataclass

from app.engine.innings import Ball, latest_revisions, overs_text
from app.engine.rules import RuleConfig


@dataclass
class BattingLine:
    batter_id: int
    runs: int = 0
    balls: int = 0
    fours: int = 0
    sixes: int = 0
    dismissals: int = 0

    @property
    def strike_rate(self) -> float:
        return round(self.runs * 100 / self.balls, 2) if self.balls else 0.0

    @property
    def not_out(self) -> bool:
        return self.dismissals == 0


@dataclass
class BowlingLine:
    bowler_id: int
    balls: int = 0
    runs: int = 0
    wickets: int = 0
    balls_per_over: int = 6

    @property
    def overs(self) -> str:
        return overs_text(self.balls, self.balls_per_over)

    @property
    def economy(self) -> float:
        return round(self.runs * self.balls_per_over / self.balls, 2) if self.balls else 0.0

    @property
    def average(self) -> float | None:
        return round(self.runs / self.wickets, 2) if self.wickets else None


def batting_stats(balls: Iterable[Ball]) -> dict[int, BattingLine]:
    out: dict[int, BattingLine] = {}
    for b in latest_revisions(balls):
        if b.batter_id is None:
            continue
        line = out.setdefault(b.batter_id, BattingLine(b.batter_id))
        line.balls += 1
        line.runs += b.runs
        line.fours += b.runs == 4
        line.sixes += b.runs == 6
        line.dismissals += b.wicket
    return out


def bowling_stats(balls: Iterable[Ball], rules: RuleConfig) -> dict[int, BowlingLine]:
    out: dict[int, BowlingLine] = {}
    for b in latest_revisions(balls):
        if b.bowler_id is None:
            continue
        line = out.setdefault(b.bowler_id, BowlingLine(b.bowler_id, balls_per_over=rules.balls_per_over))
        line.balls += 1
        line.runs += b.runs
        if b.wicket and rules.same_digit_bowler_credit:
            line.wickets += 1
    return out


def overs_bowled(balls: Iterable[Ball]) -> dict[int, set[int]]:
    """bowler_id -> set of over numbers bowled (any ball counts as bowling that over)."""
    out: dict[int, set[int]] = {}
    for b in latest_revisions(balls):
        if b.bowler_id is not None:
            out.setdefault(b.bowler_id, set()).add(b.over_no)
    return out


def can_bowl_over(bowler_id: int, over_no: int, balls: Iterable[Ball], rules: RuleConfig) -> bool:
    """False if the bowler already used their allowed overs (a repeat of the same over is fine)."""
    done = overs_bowled(balls).get(bowler_id, set())
    return over_no in done or len(done) < rules.max_overs_per_bowler
