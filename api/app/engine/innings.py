"""Innings state derived from immutable ball events and penalties.

Everything here is a pure function of its inputs, so a scorecard can always be
recomputed after an umpire correction (a new ball revision or a voided penalty).
"""

from collections.abc import Iterable
from dataclasses import dataclass, field

from app.engine.resolve import resolve_over
from app.engine.rules import RuleConfig


@dataclass(frozen=True)
class Ball:
    over_no: int
    ball_no: int  # 1..balls_per_over
    batter_digit: int
    bowler_digit: int
    runs: int
    wicket: bool
    batter_id: int | None = None
    bowler_id: int | None = None
    revision: int = 1


@dataclass(frozen=True)
class Penalty:
    """Team-total adjustment for the innings. Never counts toward player stats.

    after_over/after_ball say when it took effect ((0, 0) = before the first ball).
    """

    runs: int = 0
    wickets: int = 0
    after_over: int = 0
    after_ball: int = 0
    voided: bool = False
    reason: str = ""


@dataclass(frozen=True)
class InningsSummary:
    runs: int
    wickets: int
    legal_balls: int
    ball_runs: int
    penalty_runs: int
    penalty_wickets: int
    all_out: bool
    overs_complete: bool
    target_reached: bool
    finished: bool
    finish_reason: str | None
    balls_remaining: int
    wickets_remaining: int
    run_rate: float
    required_rate: float | None
    overs_text: str
    counted_balls: tuple[Ball, ...] = field(default=())
    ignored_balls: tuple[Ball, ...] = field(default=())


def latest_revisions(balls: Iterable[Ball]) -> list[Ball]:
    """Keep only the highest revision of each (over, ball), in play order."""
    best: dict[tuple[int, int], Ball] = {}
    for b in balls:
        key = (b.over_no, b.ball_no)
        if key not in best or b.revision > best[key].revision:
            best[key] = b
    return [best[k] for k in sorted(best)]


def overs_text(legal_balls: int, balls_per_over: int) -> str:
    return f"{legal_balls // balls_per_over}.{legal_balls % balls_per_over}"


def summarize_innings(
    balls: Iterable[Ball],
    penalties: Iterable[Penalty],
    rules: RuleConfig,
    target: int | None = None,
) -> InningsSummary:
    ordered = latest_revisions(balls)
    pens = sorted(
        (p for p in penalties if not p.voided), key=lambda p: (p.after_over, p.after_ball)
    )

    runs = wickets = legal = ball_runs = pen_runs = pen_wkts = 0
    counted: list[Ball] = []
    ignored: list[Ball] = []
    reason: str | None = None

    def apply_penalties_up_to(over_no: int, ball_no: int) -> None:
        nonlocal runs, wickets, pen_runs, pen_wkts
        while pens and (pens[0].after_over, pens[0].after_ball) <= (over_no, ball_no):
            p = pens.pop(0)
            runs += p.runs
            wickets += p.wickets
            pen_runs += p.runs
            pen_wkts += p.wickets

    def check_finished() -> str | None:
        if wickets >= rules.wickets:
            return "all_out"
        if target is not None and runs >= target:
            return "target_reached"
        if legal >= rules.max_balls:
            return "overs_complete"
        return None

    apply_penalties_up_to(0, 0)
    reason = check_finished()
    for b in ordered:
        if reason:
            ignored.append(b)
            continue
        runs += b.runs
        ball_runs += b.runs
        wickets += 1 if b.wicket else 0
        legal += 1
        counted.append(b)
        apply_penalties_up_to(b.over_no, b.ball_no)
        reason = check_finished()
    if not reason:
        # penalties scheduled after the last ball played so far
        apply_penalties_up_to(10**6, 10**6)
        reason = check_finished()

    wkts_capped = min(wickets, rules.wickets)
    rr = runs * rules.balls_per_over / legal if legal else 0.0
    balls_left = rules.max_balls - legal
    req = None
    if target is not None and reason is None and balls_left > 0:
        req = (target - runs) * rules.balls_per_over / balls_left
    return InningsSummary(
        runs=runs,
        wickets=wkts_capped,
        legal_balls=legal,
        ball_runs=ball_runs,
        penalty_runs=pen_runs,
        penalty_wickets=pen_wkts,
        all_out=wickets >= rules.wickets,
        overs_complete=legal >= rules.max_balls,
        target_reached=target is not None and runs >= target,
        finished=reason is not None,
        finish_reason=reason,
        balls_remaining=balls_left,
        wickets_remaining=rules.wickets - wkts_capped,
        run_rate=round(rr, 2),
        required_rate=round(req, 2) if req is not None else None,
        overs_text=overs_text(legal, rules.balls_per_over),
        counted_balls=tuple(counted),
        ignored_balls=tuple(ignored),
    )


def play_over(
    existing: Iterable[Ball],
    penalties: Iterable[Penalty],
    over_no: int,
    batting: list[int],
    bowling: list[int],
    rules: RuleConfig,
    target: int | None = None,
    batter_id: int | None = None,
    bowler_id: int | None = None,
) -> tuple[list[Ball], InningsSummary]:
    """Resolve an over on top of the innings so far.

    Returns (balls to persist, new summary). Balls after the innings ends
    (all out, target reached) are not returned, so they are never stored.
    """
    existing = list(existing)
    penalties = list(penalties)
    if summarize_innings(existing, penalties, rules, target).finished:
        raise ValueError("innings already finished")
    results = resolve_over(batting, bowling, rules)
    new = [
        Ball(over_no, i, bd, wd, r.runs, r.wicket, batter_id, bowler_id)
        for i, (bd, wd, r) in enumerate(zip(batting, bowling, results, strict=True), start=1)
    ]
    summary = summarize_innings(existing + new, penalties, rules, target)
    persist = [b for b in summary.counted_balls if b.over_no == over_no]
    return persist, summary
