import random

from app.engine.analytics import (
    Inn,
    MatchRecord,
    digit_counts,
    match_report,
    over_rows,
    player_report,
    season_digits,
    season_report,
    split_by_type,
    team_report,
    worm,
)
from app.engine.innings import Ball, Penalty, play_over, summarize_innings
from app.engine.rules import BATTING_PP, BOWLING_PP, NORMAL, RuleConfig

RULES = RuleConfig()  # 7 overs, powerplays in overs 2 and 6


def ball(over, n, bat, bowl, runs=None, batter=1, bowler=2):
    wicket = bat == bowl
    return Ball(over, n, bat, bowl, 0 if wicket else (bat if runs is None else runs), wicket, batter, bowler)


def play_innings(rng, number, bat_team, bowl_team, batters, bowlers, target=None, penalty=0):
    balls: list[Ball] = []
    pens = [Penalty(runs=penalty, after_over=1, after_ball=3)] if penalty else []
    for over in range(1, RULES.overs + 1):
        if summarize_innings(balls, pens, RULES, target).finished:
            break
        bat = [rng.randint(1, 6) for _ in range(6)]
        bowl = [rng.randint(1, 6) for _ in range(6)]
        new, _ = play_over(balls, pens, over, bat, bowl, RULES, target, rng.choice(batters), rng.choice(bowlers))
        balls += new
    s = summarize_innings(balls, pens, RULES, target)
    return Inn(number, bat_team, bowl_team, s.counted_balls, s.runs, s.wickets, s.penalty_runs, target)


def random_match(rng, mid, a, b, players):
    first = play_innings(rng, 1, a, b, players[a], players[b], None, penalty=rng.choice([0, 0, 3, -2]))
    second = play_innings(rng, 2, b, a, players[b], players[a], first.runs + 1, penalty=rng.choice([0, 0, 2]))
    if first.runs == second.runs:
        winner, kind = None, "tie"
    else:
        winner, kind = (a if first.runs > second.runs else b), "normal"
    tw = rng.choice([a, b])
    return MatchRecord(mid, mid, a, b, winner, kind, tw, rng.choice(["bat", "bowl"]), (first, second), RULES, mid)


def league(seed, teams=(1, 2, 3, 4)):
    rng = random.Random(seed)
    players = {t: [t * 10 + i for i in range(1, 5)] for t in teams}
    recs, mid = [], 0
    for a in teams:
        for b in teams:
            if a < b:
                mid += 1
                recs.append(random_match(rng, mid, a, b, players))
    return recs, players


# ---------- a worked example ----------
def test_a_hand_worked_innings():
    balls = (
        # over 1 (normal): 5 6 1 2 3 4 against 6 5 2 1 4 3 -> 5+6+2+...: no equal digits, runs = batter digit
        ball(1, 1, 5, 6), ball(1, 2, 6, 5), ball(1, 3, 1, 2), ball(1, 4, 2, 1), ball(1, 5, 3, 4), ball(1, 6, 4, 3),
        # over 2 (bowling powerplay): two wickets and 3 runs
        ball(2, 1, 5, 5), ball(2, 2, 6, 6), ball(2, 3, 3, 1), ball(2, 4, 1, 6), ball(2, 5, 2, 5), ball(2, 6, 4, 4),
    )
    inn = Inn(1, 10, 20, balls, runs=26, wickets=3, penalty_runs=3)  # 21 + 3 + ... penalty 3 -> total shown in the ledger
    rows = over_rows(inn, RULES)
    assert [(r["over"], r["type"], r["runs"], r["wickets"], r["balls"]) for r in rows] == [(1, NORMAL, 21, 0, 6), (2, BOWLING_PP, 6, 3, 6)]
    w = worm(inn)
    assert [x["runs"] for x in w] == [5, 11, 12, 14, 17, 21, 21, 21, 24, 25, 27, 27] and w[6]["wicket"] and not w[0]["wicket"]
    assert inn.ball_runs == 27 and inn.ball_wickets == 3
    t = split_by_type(balls, RULES)
    assert t[NORMAL] == {"balls": 6, "runs": 21, "wickets": 0} and t[BOWLING_PP] == {"balls": 6, "runs": 6, "wickets": 3}
    assert t[BATTING_PP] == {"balls": 0, "runs": 0, "wickets": 0}
    rec = MatchRecord(1, 1, 10, 20, 10, "normal", 10, "bat", (inn,), RULES)
    rep = match_report(rec, {10: "Pink", 20: "Green"})["innings"][0]
    assert rep["team"]["name"] == "Pink" and rep["ball_runs"] == 27 and rep["penalty_runs"] == 3 and rep["total"] == 26  # total as scored
    assert rep["by_type"][BOWLING_PP]["run_rate"] == 6.0 and rep["run_rate"] == 13.5


def test_digit_counts():
    d = digit_counts([1, 1, 2, 3, 3, 3, 6])
    assert d["total"] == 7 and d["counts"] == {"1": 2, "2": 1, "3": 3, "4": 0, "5": 0, "6": 1} and d["most_used"] == 3
    assert d["percent"]["3"] == 42.9 and abs(sum(d["percent"].values()) - 100) < 0.5
    assert digit_counts([2, 4])["most_used"] == 2  # a tie goes to the lower digit
    assert digit_counts([]) == {"total": 0, "counts": {str(i): 0 for i in range(1, 7)}, "percent": {str(i): 0.0 for i in range(1, 7)}, "most_used": None}


# ---------- everything adds up, for many random seasons ----------
def test_every_match_report_reconciles():
    for seed in range(40):
        recs, _ = league(seed)
        for rec in recs:
            rep = match_report(rec, {})
            for inn, i in zip(rec.innings, rep["innings"], strict=True):
                assert sum(o["runs"] for o in i["overs"]) == inn.ball_runs == (i["worm"][-1]["runs"] if i["worm"] else 0)
                assert i["total"] == inn.ball_runs + inn.penalty_runs == inn.runs  # the number in the results ledger
                assert sum(o["wickets"] for o in i["overs"]) == inn.ball_wickets == sum(w["wicket"] for w in i["worm"])
                assert sum(o["balls"] for o in i["overs"]) == len(inn.balls) == len(i["worm"]) == i["balls"]
                assert sum(v["runs"] for v in i["by_type"].values()) == inn.ball_runs
                assert sum(v["balls"] for v in i["by_type"].values()) == len(inn.balls)
                assert [o["over"] for o in i["overs"]] == sorted({o["over"] for o in i["overs"]})
                assert all(o["balls"] <= 6 for o in i["overs"])
                assert all(a["runs"] <= b["runs"] for a, b in zip(i["worm"], i["worm"][1:], strict=False))  # a worm never goes down


def test_team_reports_reconcile_with_the_ledger():
    for seed in range(30):
        recs, _ = league(seed)
        for team in (1, 2, 3, 4):
            rep = team_report(team, recs)
            mine = [r for r in recs if team in (r.team_a, r.team_b)]
            assert rep["played"] == len(mine) == rep["won"] + rep["lost"] + rep["tied"]
            batting = [i for r in mine for i in r.innings if i.batting_team == team]
            assert rep["runs_for"] == sum(i.runs for i in batting)  # the ledger's runs for this team
            assert rep["runs_against"] == sum(i.runs for r in mine for i in r.innings if i.bowling_team == team)
            by_type_runs = sum(v["runs"] for v in rep["batting_by_type"].values())
            assert by_type_runs + sum(i.penalty_runs for i in batting) == rep["runs_for"]  # penalties are the only difference
            assert sum(v["balls"] for v in rep["batting_by_type"].values()) == sum(len(i.balls) for i in batting)
            assert sum(v["runs"] for v in rep["bowling_by_type"].values()) + sum(
                i.penalty_runs for r in mine for i in r.innings if i.bowling_team == team) == rep["runs_against"]
            assert rep["batting_first"]["played"] + rep["chasing"]["played"] == rep["played"]
            assert rep["batting_first"]["won"] + rep["chasing"]["won"] == rep["won"]
            t = rep["toss"]
            assert t["won"] + t["lost"] == rep["played"] and t["chose_bat"] + t["chose_bowl"] == t["won"]
            assert rep["highest"] == max(i.runs for i in batting) and rep["lowest"] == min(i.runs for i in batting)


def test_season_report_reconciles():
    for seed in range(30):
        recs, _ = league(seed)
        rep = season_report(recs)
        decided = [r for r in recs if r.result_type == "normal"]
        assert rep["matches"] == len(recs) and rep["decided"] == len(decided) and rep["ties"] == len(recs) - len(decided)
        assert rep["bat_first_wins"] + rep["chase_wins"] == len(decided)
        assert rep["average_first_innings"] == round(sum(r.innings[0].runs for r in recs) / len(recs), 1)
        assert sum(v["balls"] for v in rep["by_type"].values()) == sum(len(i.balls) for r in recs for i in r.innings)
        assert rep["toss"]["toss_winner_won"] <= rep["toss"]["matches"]
        assert rep["toss"]["chose_bat"] + rep["toss"]["chose_bowl"] == len(recs)
        # the league's runs by type plus penalties are every innings total
        assert sum(v["runs"] for v in rep["by_type"].values()) + sum(i.penalty_runs for r in recs for i in r.innings) == sum(
            i.runs for r in recs for i in r.innings)


def test_player_reports_reconcile_with_their_figures():
    for seed in range(25):
        recs, players = league(seed)
        names = {u: f"P{u}" for ps in players.values() for u in ps}
        for user in (11, 12, 23, 34):
            rep = player_report(user, recs, names=names, form_matches=100)
            balls = [b for r in recs for i in r.innings for b in i.balls]
            faced = [b for b in balls if b.batter_id == user]
            bowled = [b for b in balls if b.bowler_id == user]
            assert sum(v["balls"] for v in rep["batting_by_type"].values()) == len(faced)
            assert sum(v["runs"] for v in rep["batting_by_type"].values()) == sum(b.runs for b in faced)
            assert sum(v["outs"] for v in rep["batting_by_type"].values()) == sum(b.wicket for b in faced)
            assert sum(v["balls"] for v in rep["bowling_by_type"].values()) == len(bowled)
            assert sum(v["wickets"] for v in rep["bowling_by_type"].values()) == sum(b.wicket for b in bowled)
            assert sum(v["runs"] for v in rep["versus_bowlers"]) == sum(b.runs for b in faced)
            assert sum(v["balls"] for v in rep["versus_batters"]) == len(bowled)
            assert sum(v["wickets"] for v in rep["versus_batters"]) == sum(b.wicket for b in bowled)
            assert sum(f["runs"] for f in rep["form"]) == sum(b.runs for b in faced)
            assert sum(f["wickets"] for f in rep["form"]) == sum(b.wicket for b in bowled)
            assert [f["match_id"] for f in rep["form"]] == sorted(f["match_id"] for f in rep["form"])
            assert rep["digits"] is None  # not asked for: never included by default
            full = player_report(user, recs, names=names, include_digits=True)["digits"]
            assert full["batting"]["total"] == len(faced) and full["bowling"]["total"] == len(bowled)
            assert sum(full["batting"]["counts"].values()) == len(faced)
            assert [v["balls"] for v in rep["versus_bowlers"]] == sorted((v["balls"] for v in rep["versus_bowlers"]), reverse=True)


def test_form_is_the_latest_matches():
    recs, _players = league(3)
    rep = player_report(11, recs, names={}, form_matches=2)
    all_ids = [f["match_id"] for f in player_report(11, recs, names={}, form_matches=100)["form"]]
    assert [f["match_id"] for f in rep["form"]] == all_ids[-2:]
    assert all(f["opponent_team"] != f["team"] for f in rep["form"])


def test_season_digits_cover_every_counted_ball():
    for seed in range(10):
        recs, _ = league(seed)
        d = season_digits(recs)
        n = sum(len(i.balls) for r in recs for i in r.innings)
        assert d["batting"]["total"] == d["bowling"]["total"] == n


def test_empty_inputs_are_fine():
    assert season_report([])["matches"] == 0 and season_report([])["average_first_innings"] is None
    rep = team_report(1, [])
    assert rep["played"] == 0 and rep["average_for"] is None and rep["batting_first"]["pct"] is None and rep["toss"]["win_pct_after_winning"] is None
    p = player_report(5, [], names={})
    assert p["form"] == [] and p["versus_bowlers"] == [] and p["batting_by_type"][NORMAL]["balls"] == 0
