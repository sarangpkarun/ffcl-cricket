import random

from app.engine.leaderboards import Perf, aggregate, leaderboards, suggest_potm

NAMES = {1: "Asha", 2: "Bala", 3: "Chitra", 4: "Dev"}


def perfs():
    return [
        Perf(10, 1, 100, 1, batted=True, runs=21, balls=6, fours=1, sixes=1, bowled=True, bowl_balls=6, bowl_runs=0, wickets=6),
        Perf(11, 1, 100, 2, batted=True, runs=9, balls=6, fours=0, sixes=0, outs=1, bowled=True, bowl_balls=6, bowl_runs=12, wickets=1),
        Perf(10, 2, 200, 1, batted=True, runs=0, balls=6, outs=6, bowled=True, bowl_balls=6, bowl_runs=21, wickets=0),
        Perf(11, 2, 200, 2, batted=True, runs=9, balls=6, outs=1),
        Perf(10, 3, 200, 1),  # played, did nothing
    ]


def test_totals():
    t = aggregate(perfs(), {2: 1})
    a, b, c = t[1], t[2], t[3]
    assert (a.matches, a.innings, a.runs, a.balls, a.fours, a.sixes, a.outs) == (2, 2, 30, 12, 1, 1, 1)
    assert (a.highest, a.highest_balls, a.not_outs, a.strike_rate, a.average) == (21, 6, 1, 250.0, 30.0)
    assert (a.wickets, a.bowl_balls, a.bowl_runs, a.best_wickets, a.best_runs, a.economy()) == (7, 12, 12, 6, 0, 6.0)
    assert b.potm == 1 and b.best_wickets == 0 and b.average == 1.29
    assert (c.matches, c.innings, c.runs, c.strike_rate, c.average, c.economy()) == (1, 0, 0, 0.0, None, 0.0)


def test_highest_score_prefers_fewer_balls_and_best_figures_prefer_fewer_runs():
    ps = [Perf(1, 1, 1, 1, batted=True, runs=20, balls=8, bowled=True, bowl_balls=6, bowl_runs=9, wickets=2),
          Perf(2, 1, 1, 2, batted=True, runs=20, balls=6, bowled=True, bowl_balls=6, bowl_runs=5, wickets=2)]
    t = aggregate(ps)[1]
    assert (t.highest, t.highest_balls, t.best_wickets, t.best_runs) == (20, 6, 2, 5)


def test_qualifiers_and_ranks():
    b = leaderboards(aggregate(perfs()), NAMES, min_balls_sr=12, min_balls_economy=12)
    assert [(r["user_id"], r["value"]) for r in b["most_runs"]] == [(1, 30), (2, 9)]
    assert [r["user_id"] for r in b["best_strike_rate"]] == [1, 2]  # both faced 12 balls
    assert [r["user_id"] for r in b["best_economy"]] == [1]
    only_one = leaderboards(aggregate(perfs()), NAMES, min_balls_sr=13, min_balls_economy=13)
    assert only_one["best_strike_rate"] == [] and only_one["best_economy"] == []
    assert [r["user_id"] for r in b["most_sixes"]] == [1] and b["most_potm"] == []


def test_equal_values_share_a_rank():
    ps = [Perf(1, u, 1, u, batted=True, runs=r, balls=6) for u, r in ((1, 10), (2, 10), (3, 7))]
    rows = leaderboards(aggregate(ps), NAMES, min_balls_sr=1, min_balls_economy=1)["most_runs"]
    assert [(r["user_id"], r["rank"]) for r in rows] == [(1, 1), (2, 1), (3, 3)]


def test_order_does_not_depend_on_input_order():
    base = perfs() * 1
    want = leaderboards(aggregate(base), NAMES, min_balls_sr=1, min_balls_economy=1)
    rnd = random.Random(7)
    for _ in range(20):
        shuffled = base[:]
        rnd.shuffle(shuffled)
        assert leaderboards(aggregate(shuffled), NAMES, min_balls_sr=1, min_balls_economy=1) == want


def test_limit():
    ps = [Perf(1, u, 1, u, batted=True, runs=u, balls=6) for u in range(1, 8)]
    assert len(leaderboards(aggregate(ps), {u: str(u) for u in range(1, 8)}, min_balls_sr=1, min_balls_economy=1, limit=3)["most_runs"]) == 3


def test_potm_suggestion():
    # 21 runs + 6 wickets (60) beats 9 runs and the others; equal scores go to fewer balls then lower id
    ranked = suggest_potm([p for p in perfs() if p.match_id == 10])
    assert ranked[0] == (1, 81)
    tie = suggest_potm([Perf(1, 5, 1, batted=True, runs=10, balls=8), Perf(1, 4, 1, batted=True, runs=10, balls=6),
                        Perf(1, 3, 1, batted=True, runs=10, balls=6)])
    assert [u for u, _ in tie] == [3, 4, 5]
