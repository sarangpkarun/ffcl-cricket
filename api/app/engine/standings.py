"""The points table. Pure functions: results in, ranked table out.

Rules (all from the season's rule set): points for a win / tie / loss, walkover and abandonment points,
and an ordered list of tie-breakers. Net run rate counts a team that was all out as having faced the full
quota of overs, as in cricket. Walkovers, abandonments and no-results never touch net run rate.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

COUNTED_FOR_NRR = ("normal", "tie")
PLAYED = ("normal", "tie", "walkover")

DEFAULT_POINTS = {"win": 2, "tie": 1, "loss": 0, "walkover_win": 2, "walkover_loss": 0, "no_result": 1, "abandoned": 1}
DEFAULT_TIEBREAKERS = ["points", "nrr", "wins", "head_to_head", "name"]
KNOWN_TIEBREAKERS = {"points", "nrr", "wins", "head_to_head", "name"}


@dataclass(frozen=True)
class StandingsRules:
    points: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_POINTS))
    tiebreakers: tuple[str, ...] = tuple(DEFAULT_TIEBREAKERS)
    qualifiers: int = 4

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> "StandingsRules":
        c = config or {}
        points = {**DEFAULT_POINTS, **(c.get("points") or {})}
        order = list(c.get("tiebreakers") or DEFAULT_TIEBREAKERS)
        unknown = set(order) - KNOWN_TIEBREAKERS
        if unknown:
            raise ValueError(f"unknown tie-breakers: {sorted(unknown)}")
        if "name" not in order:
            order.append("name")  # the table must always be fully ordered
        return cls(points=points, tiebreakers=tuple(order), qualifiers=int((c.get("knockout") or {}).get("qualifiers", 4)))


@dataclass(frozen=True)
class Outcome:
    """One finished match, as recorded in the results ledger."""

    match_id: int
    team_a: int
    team_b: int
    result_type: str  # normal | tie | walkover | abandoned | no_result
    winner: int | None = None
    a_runs: int | None = None
    a_balls: int | None = None
    a_all_out: bool = False
    b_runs: int | None = None
    b_balls: int | None = None
    b_all_out: bool = False
    order: int = 0  # for the form guide: larger = later


@dataclass(frozen=True)
class Adjustment:
    team: int
    points: int


@dataclass
class Row:
    team: int
    name: str
    played: int = 0
    won: int = 0
    lost: int = 0
    tied: int = 0
    no_result: int = 0
    match_points: int = 0
    adjustments: int = 0
    runs_for: int = 0
    balls_for: int = 0  # balls faced, an all-out innings counted as the full quota
    runs_against: int = 0
    balls_against: int = 0
    form: list[str] = field(default_factory=list)  # most recent last: W L T N
    position: int = 0
    qualified: bool = False

    @property
    def points(self) -> int:
        return self.match_points + self.adjustments

    @property
    def nrr_exact(self) -> Fraction:
        if not self.balls_for or not self.balls_against:
            return Fraction(0)
        return Fraction(self.runs_for * 6, self.balls_for) - Fraction(self.runs_against * 6, self.balls_against)

    @property
    def nrr(self) -> float:
        return round(float(self.nrr_exact), 3)


def _pts(rules: StandingsRules, kind: str) -> int:
    return rules.points[kind]


def compute_table(
    teams: dict[int, str],
    outcomes: Iterable[Outcome],
    adjustments: Iterable[Adjustment],
    rules: StandingsRules,
    quota_balls: int,
) -> list[Row]:
    """Rank every team. `teams` maps id -> name; `quota_balls` is the balls in a full innings (42)."""
    rows = {t: Row(t, name) for t, name in teams.items()}
    ordered = sorted(outcomes, key=lambda o: (o.order, o.match_id))
    for o in ordered:
        a, b = rows.get(o.team_a), rows.get(o.team_b)
        if a is None or b is None:
            continue  # a result involving a team that is not in the table (e.g. a removed team)
        if o.result_type in ("normal", "walkover") and o.winner in (o.team_a, o.team_b):
            win, lose = (a, b) if o.winner == o.team_a else (b, a)
            kind_w, kind_l = ("win", "loss") if o.result_type == "normal" else ("walkover_win", "walkover_loss")
            win.match_points += _pts(rules, kind_w)
            lose.match_points += _pts(rules, kind_l)
            win.won += 1
            lose.lost += 1
            win.form.append("W")
            lose.form.append("L")
            for r in (win, lose):
                r.played += 1
        elif o.result_type == "tie":
            for r in (a, b):
                r.match_points += _pts(rules, "tie")
                r.tied += 1
                r.played += 1
                r.form.append("T")
        elif o.result_type in ("abandoned", "no_result"):
            for r in (a, b):
                r.match_points += _pts(rules, o.result_type)
                r.no_result += 1
                r.form.append("N")
        if o.result_type in COUNTED_FOR_NRR and None not in (o.a_runs, o.a_balls, o.b_runs, o.b_balls):
            a_faced = quota_balls if o.a_all_out else o.a_balls
            b_faced = quota_balls if o.b_all_out else o.b_balls
            assert a_faced is not None and b_faced is not None and o.a_runs is not None and o.b_runs is not None
            a.runs_for += o.a_runs
            a.balls_for += a_faced
            a.runs_against += o.b_runs
            a.balls_against += b_faced
            b.runs_for += o.b_runs
            b.balls_for += b_faced
            b.runs_against += o.a_runs
            b.balls_against += a_faced
    for adj in adjustments:
        if adj.team in rows:
            rows[adj.team].adjustments += adj.points

    counted = [o for o in ordered if o.result_type in PLAYED and o.team_a in rows and o.team_b in rows]
    ranked = _rank(list(rows.values()), rules, counted)
    for i, r in enumerate(ranked, start=1):
        r.position = i
        r.qualified = i <= rules.qualifiers
        r.form = r.form[-5:]
    return ranked


def _head_to_head(group: Sequence[Row], counted: Sequence[Outcome], rules: StandingsRules) -> dict[int, int]:
    """Points each team earned in the matches played among these teams only."""
    ids = {r.team for r in group}
    pts: dict[int, int] = defaultdict(int)
    for o in counted:
        if o.team_a not in ids or o.team_b not in ids:
            continue
        if o.result_type == "tie":
            pts[o.team_a] += _pts(rules, "tie")
            pts[o.team_b] += _pts(rules, "tie")
        elif o.winner in (o.team_a, o.team_b):
            win, lose = (o.team_a, o.team_b) if o.winner == o.team_a else (o.team_b, o.team_a)
            kind_w, kind_l = ("win", "loss") if o.result_type == "normal" else ("walkover_win", "walkover_loss")
            pts[win] += _pts(rules, kind_w)
            pts[lose] += _pts(rules, kind_l)
    return {r.team: pts.get(r.team, 0) for r in group}


def _split(group: list[Row], criterion: str, counted: Sequence[Outcome], rules: StandingsRules) -> list[list[Row]]:
    """Order a tied group by one criterion, returning subgroups that are still level, best first."""
    if criterion == "points":
        key = {r.team: r.points for r in group}
    elif criterion == "nrr":
        key = {r.team: r.nrr_exact for r in group}  # type: ignore[misc]
    elif criterion == "wins":
        key = {r.team: r.won for r in group}
    elif criterion == "head_to_head":
        key = _head_to_head(group, counted, rules)  # type: ignore[assignment]
    else:  # "name": alphabetical, then id, so the order is always total
        ordered = sorted(group, key=lambda r: (r.name.casefold(), r.team))
        return [[r] for r in ordered]
    buckets: dict[Any, list[Row]] = defaultdict(list)
    for r in group:
        buckets[key[r.team]].append(r)
    return [buckets[k] for k in sorted(buckets, reverse=True)]


def _rank(rows: list[Row], rules: StandingsRules, counted: Sequence[Outcome]) -> list[Row]:
    def go(group: list[Row], criteria: Sequence[str]) -> list[Row]:
        if len(group) <= 1:
            return list(group)
        if not criteria:  # cannot happen ("name" is always last) but never leave a tie unresolved
            return sorted(group, key=lambda r: (r.name.casefold(), r.team))
        crit, rest = criteria[0], criteria[1:]
        subgroups = _split(group, crit, counted, rules)
        out: list[Row] = []
        for sub in subgroups:
            if len(sub) == len(group):  # this criterion could not separate them: try the next
                out.extend(go(sub, rest))
            elif crit == "head_to_head":  # re-run the mini-league among those still level
                out.extend(go(sub, criteria))
            else:
                out.extend(go(sub, rest if len(sub) > 1 else ()))
        return out

    return go(rows, rules.tiebreakers)
