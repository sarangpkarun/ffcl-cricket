import random
from fractions import Fraction

import pytest

from app.engine.standings import Adjustment, Outcome, StandingsRules, compute_table

QUOTA = 42  # a full 7-over innings
RULES = StandingsRules.from_config(None)


def table(teams, outcomes, adjustments=(), rules=RULES):
    return {r.team: r for r in compute_table(teams, outcomes, adjustments, rules, QUOTA)}


def ranked(teams, outcomes, adjustments=(), rules=RULES):
    return [r.name for r in compute_table(teams, outcomes, adjustments, rules, QUOTA)]


def win(mid, a, b, winner, a_runs=50, a_balls=42, a_out=False, b_runs=40, b_balls=42, b_out=True, order=0):
    return Outcome(mid, a, b, "normal", winner, a_runs, a_balls, a_out, b_runs, b_balls, b_out, order)


TEAMS = {1: "Aces", 2: "Bulls", 3: "Cobras", 4: "Dragons"}


# ---------- points ----------
def test_points_for_win_tie_and_loss():
    t = table(TEAMS, [win(1, 1, 2, 1), Outcome(2, 3, 4, "tie", None, 40, 42, True, 40, 42, True)])
    assert (t[1].points, t[2].points, t[3].points, t[4].points) == (2, 0, 1, 1)
    assert (t[1].won, t[2].lost, t[3].tied, t[4].tied) == (1, 1, 1, 1)
    assert all(r.played == 1 for r in t.values())


def test_walkover_gives_win_points_and_never_touches_net_run_rate():
    t = table(TEAMS, [Outcome(1, 1, 2, "walkover", 1)])
    assert (t[1].points, t[2].points) == (2, 0) and (t[1].won, t[2].lost) == (1, 1)
    assert t[1].nrr == 0 and t[2].nrr == 0 and t[1].balls_for == 0


@pytest.mark.parametrize("kind", ["abandoned", "no_result"])
def test_abandoned_and_no_result_share_the_points_and_count_no_nrr(kind):
    t = table(TEAMS, [Outcome(1, 1, 2, kind, None, 30, 20, False, 0, 0, False)])
    assert (t[1].points, t[2].points) == (1, 1) and t[1].no_result == t[2].no_result == 1
    assert t[1].played == 0 and t[1].nrr == 0 and t[1].form == ["N"]


def test_points_are_configurable():
    rules = StandingsRules.from_config({"points": {"win": 3, "tie": 1, "loss": 0, "walkover_win": 3}})
    t = table(TEAMS, [win(1, 1, 2, 1), Outcome(2, 3, 4, "walkover", 3)], rules=rules)
    assert (t[1].points, t[3].points, t[2].points) == (3, 3, 0)


def test_adjustments_add_and_subtract_and_show_separately():
    t = table(TEAMS, [win(1, 1, 2, 1)], [Adjustment(1, -1), Adjustment(2, 3)])
    assert (t[1].match_points, t[1].adjustments, t[1].points) == (2, -1, 1)
    assert t[2].points == 3


def test_teams_without_matches_appear_with_zeros():
    t = table(TEAMS, [])
    assert set(t) == set(TEAMS) and all(r.played == 0 and r.points == 0 and r.nrr == 0 for r in t.values())


def test_results_for_teams_not_in_the_table_are_ignored():
    t = table({1: "Aces", 2: "Bulls"}, [win(1, 1, 99, 1), win(2, 1, 2, 2)])
    assert t[1].played == 1 and t[2].points == 2


# ---------- net run rate, worked by hand ----------
def test_nrr_when_the_loser_is_all_out_counts_the_full_quota():
    # Aces 63 off 42 balls (7 overs); Bulls all out for 42 after only 30 balls, but all out = 7 overs.
    # Aces: 63/7 - 42/7 = 9 - 6 = +3.000. Bulls: 42/7 - 63/7 = -3.000.
    t = table(TEAMS, [win(1, 1, 2, 1, a_runs=63, a_balls=42, b_runs=42, b_balls=30, b_out=True)])
    assert t[1].nrr_exact == Fraction(3) and t[2].nrr_exact == Fraction(-3)
    assert t[2].balls_for == 42  # the quota, not the 30 balls actually faced


def test_nrr_when_the_chase_finishes_early_uses_the_balls_actually_faced():
    # Aces 42 off 42 balls; Bulls chase 43 in 36 balls (6 overs), not all out.
    # Bulls: 43/6 - 42/7 = 7/6 (=1.167). Aces: 42/7 - 43/6 = -7/6.
    t = table(TEAMS, [win(1, 1, 2, 2, a_runs=42, a_balls=42, a_out=False, b_runs=43, b_balls=36, b_out=False)])
    assert t[2].nrr_exact == Fraction(7, 6) and t[1].nrr_exact == Fraction(-7, 6)
    assert t[2].nrr == 1.167 and t[1].nrr == -1.167


def test_nrr_accumulates_over_several_matches_as_totals_not_averages():
    # Aces: match 1 scored 60 off 42, conceded 30 off 42 (all out); match 2 scored 20 off 42 (all out), conceded 21 off 6 balls.
    m1 = win(1, 1, 2, 1, a_runs=60, a_balls=42, b_runs=30, b_balls=42, b_out=True)
    m2 = Outcome(2, 1, 3, "normal", 3, 20, 30, True, 21, 6, False, 0)  # Aces all out (42 balls counted); Cobras reached 21 in 6 balls
    t = table(TEAMS, [m1, m2])
    # for = 80 runs / 84 balls; against = 51 runs / 48 balls
    assert t[1].nrr_exact == Fraction(80 * 6, 84) - Fraction(51 * 6, 48)


# ---------- tie-breaks ----------
def test_equal_points_are_ordered_by_net_run_rate_first():
    # Aces and Bulls each win once; Bulls' win is by a much bigger margin.
    outcomes = [win(1, 1, 3, 1, a_runs=45, b_runs=44), win(2, 2, 4, 2, a_runs=80, b_runs=20)]
    assert ranked(TEAMS, outcomes)[:2] == ["Bulls", "Aces"]


def test_equal_points_and_nrr_fall_back_to_most_wins():
    # Both teams on 2 points and the same NRR (0), but Aces got there with a win and... build via adjustments:
    outcomes = [Outcome(1, 1, 3, "tie", None, 30, 42, False, 30, 42, False), Outcome(2, 1, 4, "tie", None, 30, 42, False, 30, 42, False),
                win(3, 2, 3, 2, a_runs=50, a_balls=42, b_runs=50, b_balls=42, b_out=False)]
    # Aces: two ties = 2 points, 0 wins; Bulls: one win = 2 points, 1 win. NRR: Aces 0; Bulls 50/7-50/7 = 0.
    t = table(TEAMS, outcomes)
    assert t[1].points == t[2].points == 2 and t[1].nrr_exact == t[2].nrr_exact == 0
    assert ranked(TEAMS, outcomes)[:2] == ["Bulls", "Aces"]  # more wins


def test_the_order_of_tiebreakers_is_configurable_head_to_head_before_nrr():
    # Aces beat Bulls narrowly; Bulls beat Cobras hugely. Aces and Bulls both end on 2 points.
    outcomes = [win(1, 1, 2, 1, a_runs=45, b_runs=44), win(2, 2, 3, 2, a_runs=90, b_runs=10)]
    assert ranked(TEAMS, outcomes)[:2] == ["Bulls", "Aces"]  # default: NRR first
    h2h_first = StandingsRules.from_config({"tiebreakers": ["points", "head_to_head", "nrr", "name"]})
    assert ranked(TEAMS, outcomes, rules=h2h_first)[:2] == ["Aces", "Bulls"]  # Aces beat Bulls


def test_three_way_tie_is_resolved_by_the_mini_league_among_the_tied_teams():
    # Aces beat Bulls and Cobras, Bulls beat Cobras; adjustments level everybody on 4 points.
    outcomes = [win(1, 1, 2, 1), win(2, 1, 3, 1), win(3, 2, 3, 2)]
    adj = [Adjustment(2, 2), Adjustment(3, 4)]
    rules = StandingsRules.from_config({"tiebreakers": ["points", "head_to_head", "name"]})
    t = table(TEAMS, outcomes, adj, rules)
    assert [t[i].points for i in (1, 2, 3)] == [4, 4, 4]
    assert ranked(TEAMS, outcomes, adj, rules)[:3] == ["Aces", "Bulls", "Cobras"]


def test_a_circular_head_to_head_cannot_be_separated_so_the_next_rule_decides():
    outcomes = [win(1, 1, 2, 1), win(2, 2, 3, 2), win(3, 3, 1, 3)]  # Aces > Bulls > Cobras > Aces
    rules = StandingsRules.from_config({"tiebreakers": ["points", "head_to_head", "name"]})
    assert ranked({1: "Aces", 2: "Bulls", 3: "Cobras"}, outcomes, rules=rules) == ["Aces", "Bulls", "Cobras"]  # by name
    zed = {1: "Zebras", 2: "Bulls", 3: "Aces"}
    assert ranked(zed, outcomes, rules=rules) == ["Aces", "Bulls", "Zebras"]  # name, not input order


def test_head_to_head_is_rerun_among_the_teams_still_level():
    # Aces and Bulls each beat Cobras and Dragons and tied each other; Cobras beat Dragons.
    outcomes = [win(1, 1, 3, 1), win(2, 1, 4, 1), win(3, 2, 3, 2), win(4, 2, 4, 2),
                Outcome(5, 1, 2, "tie", None, 30, 42, False, 30, 42, False), win(6, 3, 4, 3)]
    adj = [Adjustment(3, 3), Adjustment(4, 5)]  # level everyone on 5 points
    rules = StandingsRules.from_config({"tiebreakers": ["points", "head_to_head", "name"]})
    t = table(TEAMS, outcomes, adj, rules)
    assert {r.points for r in t.values()} == {5}
    assert ranked(TEAMS, outcomes, adj, rules) == ["Aces", "Bulls", "Cobras", "Dragons"]  # A,B level on h2h -> name; C>D


def test_unknown_tiebreakers_are_rejected_and_name_is_always_appended():
    with pytest.raises(ValueError, match="unknown"):
        StandingsRules.from_config({"tiebreakers": ["points", "coin_toss"]})
    assert StandingsRules.from_config({"tiebreakers": ["points"]}).tiebreakers == ("points", "name")


def test_top_n_are_marked_as_qualified_and_positions_are_1_to_n():
    rules = StandingsRules.from_config({"knockout": {"qualifiers": 2}})
    rows = compute_table(TEAMS, [win(1, 1, 2, 1), win(2, 3, 4, 3)], [], rules, QUOTA)
    assert [r.position for r in rows] == [1, 2, 3, 4] and [r.qualified for r in rows] == [True, True, False, False]


def test_form_guide_is_the_last_five_in_match_order_whatever_order_they_arrive_in():
    # Aces win matches 1, 3, 5, 7 and lose 2, 4, 6, 8: the last five are matches 4..8 = L W L W L
    outs = [win(i, 1, 2, 1 if i % 2 else 2, order=i) for i in range(1, 9)]
    assert table(TEAMS, outs)[1].form == ["L", "W", "L", "W", "L"]
    assert table(TEAMS, list(reversed(outs)))[1].form == ["L", "W", "L", "W", "L"]
    assert table(TEAMS, outs)[2].form == ["W", "L", "W", "L", "W"]
    mixed = [win(1, 1, 2, 1, order=1), Outcome(2, 1, 3, "tie", None, 30, 42, False, 30, 42, False, 2),
             Outcome(3, 1, 4, "abandoned", order=3), Outcome(4, 1, 2, "walkover", 2, order=4)]
    assert table(TEAMS, mixed)[1].form == ["W", "T", "N", "L"]


# ---------- properties ----------
def random_outcomes(rng, n_teams, n_matches):
    ids = list(range(1, n_teams + 1))
    out = []
    for m in range(n_matches):
        a, b = rng.sample(ids, 2)
        kind = rng.choice(["normal", "normal", "tie", "walkover", "abandoned", "no_result"])
        ar, br = rng.randint(0, 80), rng.randint(0, 80)
        winner = rng.choice([a, b]) if kind in ("normal", "walkover") else None
        full = kind in ("normal", "tie")
        out.append(Outcome(m + 1, a, b, kind, winner, ar if full else None, rng.randint(1, 42) if full else None, rng.random() < .4,
                           br if full else None, rng.randint(1, 42) if full else None, rng.random() < .4, order=m))
    return out


def test_every_match_hands_out_exactly_two_points_with_the_default_scoring():
    rng = random.Random(1)
    for _ in range(60):
        outs = random_outcomes(rng, rng.randint(2, 8), rng.randint(0, 30))
        names = {i: f"T{i}" for i in range(1, 9)}
        rows = compute_table(names, outs, [], RULES, QUOTA)
        assert sum(r.match_points for r in rows) == 2 * len(outs)  # win 2+0, tie 1+1, abandoned 1+1
        assert sum(r.won for r in rows) == sum(r.lost for r in rows)
        assert sorted(r.position for r in rows) == list(range(1, len(rows) + 1))


def test_the_table_does_not_depend_on_the_order_results_or_teams_arrive_in():
    rng = random.Random(2)
    for _ in range(40):
        outs = random_outcomes(rng, 6, 20)
        names = {i: f"T{i}" for i in range(1, 7)}
        a = [(r.team, r.points, r.nrr_exact, r.position, tuple(r.form)) for r in compute_table(names, outs, [], RULES, QUOTA)]
        shuffled = outs[:]
        rng.shuffle(shuffled)
        items = list(names.items())
        rng.shuffle(items)
        b = [(r.team, r.points, r.nrr_exact, r.position, tuple(r.form)) for r in compute_table(dict(items), shuffled, [], RULES, QUOTA)]
        assert a == b


def test_ranking_is_consistent_with_the_first_criteria():
    rng = random.Random(3)
    for _ in range(40):
        outs = random_outcomes(rng, 6, 18)
        rows = compute_table({i: f"T{i}" for i in range(1, 7)}, outs, [], RULES, QUOTA)
        pts = [(r.points, r.nrr_exact) for r in rows]
        assert pts == sorted(pts, reverse=True)  # points, then net run rate, never out of order
