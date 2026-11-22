"""Season and career statistics from per-match performances. Pure: no database.

A `Perf` is one player in one match. Everything else (totals, highest score, best figures, the
leaderboards) is derived from a list of them, so a corrected ball is reflected the next time it is built.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from fractions import Fraction


@dataclass
class Perf:
    match_id: int
    user_id: int
    team_id: int
    when: int = 0  # sort key for "most recent team" and history, e.g. epoch seconds
    batted: bool = False
    runs: int = 0
    balls: int = 0
    fours: int = 0
    sixes: int = 0
    outs: int = 0
    bowled: bool = False
    bowl_balls: int = 0
    bowl_runs: int = 0
    wickets: int = 0


@dataclass
class Totals:
    user_id: int
    team_id: int = 0  # the team of the player's latest match in scope
    matches: int = 0
    innings: int = 0
    runs: int = 0
    balls: int = 0
    fours: int = 0
    sixes: int = 0
    outs: int = 0
    highest: int = 0
    highest_balls: int = 0
    bowl_innings: int = 0
    bowl_balls: int = 0
    bowl_runs: int = 0
    wickets: int = 0
    best_wickets: int = 0
    best_runs: int = 0
    potm: int = 0
    _last: int = field(default=-1, repr=False)

    @property
    def not_outs(self) -> int:
        return self.innings - min(self.innings, self.outs)

    @property
    def strike_rate(self) -> float:
        return round(self.runs * 100 / self.balls, 2) if self.balls else 0.0

    @property
    def average(self) -> float | None:
        return round(self.runs / self.outs, 2) if self.outs else None

    def economy(self, balls_per_over: int = 6) -> float:
        return round(self.bowl_runs * balls_per_over / self.bowl_balls, 2) if self.bowl_balls else 0.0


def aggregate(perfs: Iterable[Perf], potm_counts: dict[int, int] | None = None) -> dict[int, Totals]:
    out: dict[int, Totals] = {}
    for p in sorted(perfs, key=lambda x: (x.when, x.match_id)):
        t = out.setdefault(p.user_id, Totals(p.user_id))
        t.matches += 1
        t.team_id = p.team_id  # sorted by time, so the last one wins
        if p.batted:
            t.innings += 1
            t.runs += p.runs
            t.balls += p.balls
            t.fours += p.fours
            t.sixes += p.sixes
            t.outs += p.outs
            if p.runs > t.highest or (p.runs == t.highest and t.highest_balls and p.balls < t.highest_balls):
                t.highest, t.highest_balls = p.runs, p.balls
        if p.bowled:
            t.bowl_innings += 1
            t.bowl_balls += p.bowl_balls
            t.bowl_runs += p.bowl_runs
            t.wickets += p.wickets
            if p.wickets > t.best_wickets or (p.wickets == t.best_wickets and p.wickets and p.bowl_runs < t.best_runs):
                t.best_wickets, t.best_runs = p.wickets, p.bowl_runs
    for uid, n in (potm_counts or {}).items():
        if uid in out:
            out[uid].potm = n
    return out


CATEGORIES: list[tuple[str, str]] = [
    ("most_runs", "Most runs"),
    ("most_wickets", "Most wickets"),
    ("highest_score", "Highest score"),
    ("best_strike_rate", "Best strike rate"),
    ("best_economy", "Best economy"),
    ("most_sixes", "Most sixes"),
    ("most_fours", "Most fours"),
    ("most_potm", "Player of the match awards"),
]


def _ranked(rows: list[tuple[tuple, Totals, float | int, str]], limit: int) -> list[dict]:
    """rows: (sort key, totals, shown value, detail). Equal keys share a rank."""
    rows.sort(key=lambda r: r[0])
    out, rank, prev = [], 0, None
    for i, (key, t, value, detail) in enumerate(rows[:limit]):
        if key[:1] != prev:
            rank = i + 1
            prev = key[:1]
        out.append({"rank": rank, "user_id": t.user_id, "team_id": t.team_id, "value": value, "detail": detail})
    return out


def leaderboards(totals: dict[int, Totals], names: dict[int, str], *, min_balls_sr: int, min_balls_economy: int,
                 balls_per_over: int = 6, limit: int = 10) -> dict[str, list[dict]]:
    """Every category, best first. Keys end in the player's name so the order is always total."""
    ts = list(totals.values())
    nm = lambda t: names.get(t.user_id, "")
    out: dict[str, list[dict]] = {}
    out["most_runs"] = _ranked([((-t.runs, t.balls, nm(t)), t, t.runs, f"{t.innings} inn, SR {t.strike_rate:.2f}")
                                for t in ts if t.runs > 0], limit)
    out["most_wickets"] = _ranked([((-t.wickets, t.bowl_runs, nm(t)), t, t.wickets,
                                    f"{t.bowl_runs} runs, econ {t.economy(balls_per_over):.2f}") for t in ts if t.wickets > 0], limit)
    out["highest_score"] = _ranked([((-t.highest, t.highest_balls, nm(t)), t, t.highest, f"off {t.highest_balls} balls")
                                    for t in ts if t.highest > 0], limit)
    out["best_strike_rate"] = _ranked(
        [((-Fraction(t.runs * 100, t.balls), -t.runs, nm(t)), t, t.strike_rate, f"{t.runs} off {t.balls}")
         for t in ts if t.balls >= min_balls_sr and t.balls > 0], limit)
    out["best_economy"] = _ranked(
        [((Fraction(t.bowl_runs * balls_per_over, t.bowl_balls), -t.wickets, nm(t)), t, t.economy(balls_per_over),
          f"{t.bowl_runs} off {t.bowl_balls} balls") for t in ts if t.bowl_balls >= min_balls_economy and t.bowl_balls > 0], limit)
    out["most_sixes"] = _ranked([((-t.sixes, t.balls, nm(t)), t, t.sixes, f"{t.runs} runs") for t in ts if t.sixes > 0], limit)
    out["most_fours"] = _ranked([((-t.fours, t.balls, nm(t)), t, t.fours, f"{t.runs} runs") for t in ts if t.fours > 0], limit)
    out["most_potm"] = _ranked([((-t.potm, nm(t)), t, t.potm, f"{t.matches} matches") for t in ts if t.potm > 0], limit)
    return out


def suggest_potm(perfs: Iterable[Perf]) -> list[tuple[int, int]]:
    """Best performers first: runs + 10 per wicket. Ties go to fewer balls used, then the lower id."""
    scored = [(p.runs + 10 * p.wickets, p.balls + p.bowl_balls, p.user_id) for p in perfs]
    scored.sort(key=lambda s: (-s[0], s[1], s[2]))
    return [(uid, score) for score, _, uid in scored]
