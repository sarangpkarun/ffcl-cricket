"""Match, team, player and season analytics. Pure: no database.

Everything here is derived from the same counted balls the scorecard uses, so the totals always agree with it:
over-by-over runs add up to the innings' ball runs, and ball runs plus penalty runs are the innings total (the
number in the results ledger). Penalties are team adjustments and never appear in a player's figures.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from app.engine.innings import Ball
from app.engine.rules import BATTING_PP, BOWLING_PP, NORMAL, RuleConfig

TYPES = (NORMAL, BOWLING_PP, BATTING_PP)
DIGITS = (1, 2, 3, 4, 5, 6)


@dataclass(frozen=True)
class Inn:
    number: int
    batting_team: int
    bowling_team: int
    balls: tuple[Ball, ...]  # the balls that counted, in play order
    runs: int  # innings total: ball runs plus penalty runs
    wickets: int  # including penalty wickets, capped at the match limit
    penalty_runs: int = 0
    target: int | None = None

    @property
    def ball_runs(self) -> int:
        return sum(b.runs for b in self.balls)

    @property
    def ball_wickets(self) -> int:
        return sum(1 for b in self.balls if b.wicket)


@dataclass(frozen=True)
class MatchRecord:
    match_id: int
    match_no: int
    team_a: int
    team_b: int
    winner: int | None  # None for a tie or no result
    result_type: str | None
    toss_winner: int | None
    toss_decision: str | None
    innings: tuple[Inn, ...]
    rules: RuleConfig = field(default_factory=RuleConfig)
    when: int = 0

    def other(self, team: int) -> int:
        return self.team_b if team == self.team_a else self.team_a


def rate(runs: int, balls: int, per: int) -> float:
    return round(runs * per / balls, 2) if balls else 0.0


def pct(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


# ---------- one match ----------
def over_rows(inn: Inn, rules: RuleConfig) -> list[dict[str, Any]]:
    by_over: dict[int, dict[str, Any]] = {}
    for b in inn.balls:
        r = by_over.setdefault(b.over_no, {"over": b.over_no, "type": rules.over_type(b.over_no), "runs": 0, "wickets": 0, "balls": 0})
        r["runs"] += b.runs
        r["wickets"] += 1 if b.wicket else 0
        r["balls"] += 1
    return [by_over[k] for k in sorted(by_over)]


def worm(inn: Inn) -> list[dict[str, Any]]:
    """Cumulative runs after every ball (penalty runs are shown separately, not in the line)."""
    out, total = [], 0
    for i, b in enumerate(inn.balls, start=1):
        total += b.runs
        out.append({"ball": i, "over": b.over_no, "runs": total, "wicket": b.wicket})
    return out


def split_by_type(balls: Iterable[Ball], rules: RuleConfig) -> dict[str, dict[str, int]]:
    out = {t: {"balls": 0, "runs": 0, "wickets": 0} for t in TYPES}
    for b in balls:
        row = out[rules.over_type(b.over_no)]
        row["balls"] += 1
        row["runs"] += b.runs
        row["wickets"] += 1 if b.wicket else 0
    return out


def match_report(rec: MatchRecord, team_names: dict[int, str]) -> dict[str, Any]:
    rules = rec.rules
    per = rules.balls_per_over
    innings: list[dict[str, Any]] = []
    for inn in rec.innings:
        rows = over_rows(inn, rules)
        innings.append({
            "number": inn.number, "team": {"id": inn.batting_team, "name": team_names.get(inn.batting_team)},
            "total": inn.runs, "ball_runs": inn.ball_runs, "penalty_runs": inn.penalty_runs, "wickets": inn.wickets,
            "balls": len(inn.balls), "run_rate": rate(inn.ball_runs, len(inn.balls), per), "target": inn.target,
            "overs": rows, "worm": worm(inn),
            "by_type": {t: {**v, "run_rate": rate(v["runs"], v["balls"], per)} for t, v in split_by_type(inn.balls, rules).items()},
        })
    all_overs: list[dict[str, Any]] = [r for i in innings for r in i["overs"]]
    best = max(all_overs, key=lambda r: (r["runs"], -r["over"]), default=None)
    return {"match_id": rec.match_id, "overs_in_match": rules.overs, "balls_per_over": per, "innings": innings,
            "biggest_over": best, "over_types": {str(o): rules.over_type(o) for o in range(1, rules.overs + 1)}}


# ---------- a team over a season ----------
def _won(rec: MatchRecord, team: int) -> bool:
    return rec.result_type == "normal" and rec.winner == team


def team_report(team: int, records: list[MatchRecord]) -> dict[str, Any]:
    mine = [r for r in records if team in (r.team_a, r.team_b)]
    played = len(mine)
    won = sum(_won(r, team) for r in mine)
    tied = sum(r.result_type == "tie" for r in mine)
    first = [r for r in mine if any(i.number == 1 and i.batting_team == team for i in r.innings)]
    chase = [r for r in mine if r not in first]
    scored = [i.runs for r in mine for i in r.innings if i.batting_team == team]
    conceded = [i.runs for r in mine for i in r.innings if i.bowling_team == team]
    bat = {t: {"balls": 0, "runs": 0, "wickets": 0} for t in TYPES}
    bowl = {t: {"balls": 0, "runs": 0, "wickets": 0} for t in TYPES}
    per = mine[0].rules.balls_per_over if mine else 6
    for r in mine:
        for i in r.innings:
            target = bat if i.batting_team == team else bowl if i.bowling_team == team else None
            if target is None:
                continue
            for t, v in split_by_type(i.balls, r.rules).items():
                for k in ("balls", "runs", "wickets"):
                    target[t][k] += v[k]
    won_toss = [r for r in mine if r.toss_winner == team]
    lost_toss = [r for r in mine if r.toss_winner is not None and r.toss_winner != team]
    return {
        "played": played, "won": won, "lost": sum(r.result_type == "normal" and r.winner != team for r in mine), "tied": tied,
        "batting_first": {"played": len(first), "won": sum(_won(r, team) for r in first), "pct": pct(sum(_won(r, team) for r in first), len(first))},
        "chasing": {"played": len(chase), "won": sum(_won(r, team) for r in chase), "pct": pct(sum(_won(r, team) for r in chase), len(chase))},
        "runs_for": sum(scored), "runs_against": sum(conceded),
        "average_for": round(sum(scored) / len(scored), 1) if scored else None,
        "average_against": round(sum(conceded) / len(conceded), 1) if conceded else None,
        "highest": max(scored) if scored else None, "lowest": min(scored) if scored else None,
        "batting_by_type": {t: {**v, "run_rate": rate(v["runs"], v["balls"], per)} for t, v in bat.items()},
        "bowling_by_type": {t: {**v, "economy": rate(v["runs"], v["balls"], per)} for t, v in bowl.items()},
        "toss": {"won": len(won_toss), "lost": len(lost_toss),
                 "chose_bat": sum(r.toss_decision == "bat" for r in won_toss), "chose_bowl": sum(r.toss_decision == "bowl" for r in won_toss),
                 "win_pct_after_winning": pct(sum(_won(r, team) for r in won_toss), len(won_toss)),
                 "win_pct_after_losing": pct(sum(_won(r, team) for r in lost_toss), len(lost_toss))},
    }


# ---------- a season ----------
def season_report(records: list[MatchRecord]) -> dict[str, Any]:
    decided = [r for r in records if r.result_type == "normal"]
    first = [i for r in records for i in r.innings if i.number == 1]
    second = [i for r in records for i in r.innings if i.number == 2]
    toss_matches = [r for r in decided if r.toss_winner is not None]
    bat_first_wins = sum(any(i.number == 1 and i.batting_team == r.winner for i in r.innings) for r in decided)
    chases = sum(any(i.number == 2 and i.batting_team == r.winner for i in r.innings) for r in decided)
    per = records[0].rules.balls_per_over if records else 6
    types = {t: {"balls": 0, "runs": 0, "wickets": 0} for t in TYPES}
    for r in records:
        for i in r.innings:
            for t, v in split_by_type(i.balls, r.rules).items():
                for k in ("balls", "runs", "wickets"):
                    types[t][k] += v[k]
    totals = [i.runs for r in records for i in r.innings]
    return {
        "matches": len(records), "decided": len(decided), "ties": sum(r.result_type == "tie" for r in records),
        "average_first_innings": round(sum(i.runs for i in first) / len(first), 1) if first else None,
        "average_second_innings": round(sum(i.runs for i in second) / len(second), 1) if second else None,
        "highest_total": max(totals) if totals else None, "lowest_total": min(totals) if totals else None,
        "bat_first_wins": bat_first_wins, "chase_wins": chases,
        "bat_first_pct": pct(bat_first_wins, len(decided)), "chase_pct": pct(chases, len(decided)),
        "toss": {"matches": len(toss_matches), "toss_winner_won": sum(r.toss_winner == r.winner for r in toss_matches),
                 "toss_winner_pct": pct(sum(r.toss_winner == r.winner for r in toss_matches), len(toss_matches)),
                 "chose_bat": sum(r.toss_decision == "bat" for r in records), "chose_bowl": sum(r.toss_decision == "bowl" for r in records)},
        "by_type": {t: {**v, "run_rate": rate(v["runs"], v["balls"], per),
                        "wickets_per_over": round(v["wickets"] * per / v["balls"], 2) if v["balls"] else 0.0} for t, v in types.items()},
    }


# ---------- digits: only ever reported for a finished season ----------
def digit_counts(digits: Iterable[int]) -> dict[str, Any]:
    c = Counter(digits)
    total = sum(c.values())
    return {"total": total, "counts": {str(d): c.get(d, 0) for d in DIGITS},
            "percent": {str(d): (round(100 * c.get(d, 0) / total, 1) if total else 0.0) for d in DIGITS},
            "most_used": max(DIGITS, key=lambda d: (c.get(d, 0), -d)) if total else None}


def season_digits(records: list[MatchRecord]) -> dict[str, Any]:
    bats, bowls = [], []
    for r in records:
        for i in r.innings:
            bats += [b.batter_digit for b in i.balls]
            bowls += [b.bowler_digit for b in i.balls]
    return {"batting": digit_counts(bats), "bowling": digit_counts(bowls)}


# ---------- one player ----------
def player_report(user: int, records: list[MatchRecord], *, names: dict[int, str], include_digits: bool = False,
                  form_matches: int = 10) -> dict[str, Any]:
    per = records[0].rules.balls_per_over if records else 6
    bat = {t: {"balls": 0, "runs": 0, "outs": 0} for t in TYPES}
    bowl = {t: {"balls": 0, "runs": 0, "wickets": 0} for t in TYPES}
    vs_bowlers: dict[int, dict[str, int]] = defaultdict(lambda: {"balls": 0, "runs": 0, "outs": 0})
    vs_batters: dict[int, dict[str, int]] = defaultdict(lambda: {"balls": 0, "runs": 0, "wickets": 0})
    form, bat_digits, bowl_digits = [], [], []
    for r in sorted(records, key=lambda x: (x.when, x.match_id)):
        row = {"match_id": r.match_id, "match_no": r.match_no, "runs": 0, "balls": 0, "out": False,
               "bowl_balls": 0, "runs_conceded": 0, "wickets": 0}
        seen, team = False, None
        for i in r.innings:
            for b in i.balls:
                t = r.rules.over_type(b.over_no)
                if b.batter_id == user:
                    seen, team = True, i.batting_team
                    bat[t]["balls"] += 1
                    bat[t]["runs"] += b.runs
                    bat[t]["outs"] += 1 if b.wicket else 0
                    row["balls"] += 1
                    row["runs"] += b.runs
                    row["out"] = row["out"] or b.wicket
                    bat_digits.append(b.batter_digit)
                    if b.bowler_id is not None:
                        h = vs_bowlers[b.bowler_id]
                        h["balls"] += 1
                        h["runs"] += b.runs
                        h["outs"] += 1 if b.wicket else 0
                if b.bowler_id == user:
                    seen, team = True, i.bowling_team
                    bowl[t]["balls"] += 1
                    bowl[t]["runs"] += b.runs
                    bowl[t]["wickets"] += 1 if b.wicket else 0
                    row["bowl_balls"] += 1
                    row["runs_conceded"] += b.runs
                    row["wickets"] += 1 if b.wicket else 0
                    bowl_digits.append(b.bowler_digit)
                    if b.batter_id is not None:
                        h2 = vs_batters[b.batter_id]
                        h2["balls"] += 1
                        h2["runs"] += b.runs
                        h2["wickets"] += 1 if b.wicket else 0
        if seen and team is not None:
            form.append({**row, "team": team, "opponent_team": r.other(team)})
    out: dict[str, Any] = {
        "batting_by_type": {t: {**v, "strike_rate": rate(v["runs"], v["balls"], 100)} for t, v in bat.items()},
        "bowling_by_type": {t: {**v, "economy": rate(v["runs"], v["balls"], per)} for t, v in bowl.items()},
        "form": form[-form_matches:],
        "versus_bowlers": [{"user_id": u, "name": names.get(u), **v, "strike_rate": rate(v["runs"], v["balls"], 100)}
                           for u, v in sorted(vs_bowlers.items(), key=lambda kv: (-kv[1]["balls"], kv[0]))],
        "versus_batters": [{"user_id": u, "name": names.get(u), **v, "economy": rate(v["runs"], v["balls"], per)}
                           for u, v in sorted(vs_batters.items(), key=lambda kv: (-kv[1]["balls"], kv[0]))],
    }
    out["digits"] = {"batting": digit_counts(bat_digits), "bowling": digit_counts(bowl_digits)} if include_digits else None
    return out


