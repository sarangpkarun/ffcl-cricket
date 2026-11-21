import random

import pytest

from app.engine import (
    Ball,
    Penalty,
    RuleConfig,
    batting_stats,
    bowling_stats,
    can_bowl_over,
    decide_match,
    parse_digits,
    play_over,
    summarize_innings,
    target_for,
)

R = RuleConfig()


def ball(o, n, bd, wd, bat=1, bowl=10, rev=1):
    wicket = bd == wd
    return Ball(o, n, bd, wd, 0 if wicket else bd, wicket, bat, bowl, rev)


def over(o, bat_digits, bowl_digits, bat=1, bowl=10):
    return [ball(o, i, b, w, bat, bowl) for i, (b, w) in enumerate(zip(bat_digits, bowl_digits), 1)]


# ---------- digits parsing ----------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("123456", [1, 2, 3, 4, 5, 6]),
        ("1 2 3 4 5 6", [1, 2, 3, 4, 5, 6]),
        ("1️⃣2️⃣3️⃣4️⃣5️⃣6️⃣", [1, 2, 3, 4, 5, 6]),
        ([1, 2, 3], [1, 2, 3]),
        ("12a456", None),
        ("", []),
    ],
)
def test_parse_digits(raw, expected):
    assert parse_digits(raw) == expected


# ---------- innings basics ----------
def test_summary_totals_and_rates():
    balls = over(1, [4, 4, 4, 4, 4, 4], [1, 1, 1, 1, 1, 1]) + over(2, [2, 3, 3, 1, 1, 1], [1, 1, 2, 2, 2, 2])
    s = summarize_innings(balls, [], R)
    assert s.legal_balls == 12 and s.overs_text == "2.0"
    assert s.runs == 24 + 11
    assert s.wickets == 0


def test_wickets_counted_and_all_out_stops_innings():
    balls = over(1, [1] * 6, [1] * 6)  # six wickets
    s = summarize_innings(balls, [], R)
    assert s.wickets == 6 and not s.finished
    more = balls + over(2, [2, 3, 4, 5, 6, 1], [2, 9, 9, 9, 9, 9])  # wicket on ball 1 -> 7th
    s = summarize_innings(more, [], R)
    assert s.all_out and s.finished and s.finish_reason == "all_out"
    assert s.legal_balls == 7 and len(s.ignored_balls) == 5
    assert s.wickets_remaining == 0


def test_overs_complete_after_seven_overs():
    balls = [b for o in range(1, 8) for b in over(o, [1] * 6, [2] * 6)]
    s = summarize_innings(balls, [], R)
    assert s.overs_complete and s.finish_reason == "overs_complete"
    assert s.runs == 42 and s.legal_balls == 42 and s.overs_text == "7.0"


def test_target_reached_stops_play_mid_over():
    prior = over(1, [6] * 6, [1] * 6)  # 36 runs
    s = summarize_innings(prior, [], R, target=30)
    assert s.finished and s.target_reached and s.legal_balls == 5
    assert len(s.ignored_balls) == 1


def test_required_rate_and_remaining():
    prior = over(1, [2] * 6, [1] * 6)  # 12 runs after 6 balls
    s = summarize_innings(prior, [], R, target=33)
    assert s.balls_remaining == 36 and s.required_rate == 3.5 and s.run_rate == 12.0


# ---------- play_over ----------
def test_play_over_persists_only_counted_balls_when_all_out():
    existing = over(1, [1] * 6, [1] * 6)  # 6 wickets
    persist, s = play_over(existing, [], 2, [3] * 6, [3] * 6, R, batter_id=1, bowler_id=10)
    assert len(persist) == 1 and s.all_out


def test_play_over_stops_at_target():
    existing = over(1, [4] * 6, [1] * 6)  # 24
    persist, s = play_over(existing, [], 2, [6] * 6, [1] * 6, R, target=33)
    assert [b.runs for b in persist] == [6, 6] and s.target_reached and s.runs == 36


def test_play_over_rejects_finished_innings():
    existing = [b for o in range(1, 8) for b in over(o, [1] * 6, [2] * 6)]
    with pytest.raises(ValueError):
        play_over(existing, [], 8, [1] * 6, [2] * 6, R)


# ---------- penalties ----------
def test_penalties_hit_team_total_not_player_stats():
    balls = over(1, [4] * 6, [1] * 6)
    pen = [Penalty(runs=6, after_over=1, after_ball=6, reason="late submission")]
    s = summarize_innings(balls, pen, R)
    assert s.runs == 30 and s.ball_runs == 24 and s.penalty_runs == 6
    assert batting_stats(balls)[1].runs == 24  # unchanged by penalty
    assert bowling_stats(balls, R)[10].runs == 24


def test_penalty_wicket_counts_for_team_not_bowler():
    balls = over(1, [2] * 6, [1] * 6)
    s = summarize_innings(balls, [Penalty(wickets=1, after_over=1, after_ball=6)], R)
    assert s.wickets == 1
    assert bowling_stats(balls, R)[10].wickets == 0


def test_voided_penalty_is_ignored():
    s = summarize_innings(over(1, [2] * 6, [1] * 6), [Penalty(runs=5, voided=True)], R)
    assert s.runs == 12 and s.penalty_runs == 0


def test_penalty_before_first_ball_applies():
    s = summarize_innings(over(1, [2] * 6, [1] * 6), [Penalty(runs=-3)], R)
    assert s.runs == 9


def test_penalty_can_end_chase_at_exact_position():
    balls = over(1, [4, 4, 4, 4, 4, 4], [1] * 6)
    # target 30: 24 from balls + 6 penalty after ball 3 hits 18 -> not yet; ball 6 total 30
    s = summarize_innings(balls, [Penalty(runs=6, after_over=1, after_ball=3)], R, target=30)
    assert s.target_reached and s.legal_balls == 6
    s2 = summarize_innings(balls, [Penalty(runs=12, after_over=1, after_ball=3)], R, target=30)
    assert s2.legal_balls == 5 and len(s2.ignored_balls) == 1


# ---------- corrections ----------
def test_latest_revision_wins_and_recomputes():
    balls = over(1, [4] * 6, [1] * 6)
    fixed = balls + [Ball(1, 3, 6, 1, 6, False, 1, 10, revision=2)]
    assert summarize_innings(balls, [], R).runs == 24
    assert summarize_innings(fixed, [], R).runs == 26
    assert batting_stats(fixed)[1].sixes == 1 and batting_stats(fixed)[1].balls == 6


def test_correction_turning_wicket_into_runs():
    balls = over(1, [3, 2, 2, 2, 2, 2], [3, 1, 1, 1, 1, 1])
    assert summarize_innings(balls, [], R).wickets == 1
    fix = balls + [Ball(1, 1, 3, 5, 3, False, 1, 10, revision=2)]
    s = summarize_innings(fix, [], R)
    assert s.wickets == 0 and s.runs == 13


# ---------- stats ----------
def test_batting_and_bowling_lines():
    balls = over(1, [6, 4, 3, 3, 1, 2], [1, 1, 3, 2, 9, 9], bat=1, bowl=10)
    b = batting_stats(balls)[1]
    assert (b.runs, b.balls, b.sixes, b.fours, b.dismissals) == (16, 6, 1, 1, 1)
    assert b.strike_rate == 266.67 and not b.not_out
    w = bowling_stats(balls, R)[10]
    assert (w.runs, w.balls, w.wickets, w.overs, w.economy) == (16, 6, 1, "1.0", 16.0)
    assert w.average == 16.0


def test_no_bowler_credit_when_rule_disabled():
    rules = RuleConfig(same_digit_bowler_credit=False)
    balls = over(1, [3, 2, 2, 2, 2, 2], [3, 1, 1, 1, 1, 1])
    assert bowling_stats(balls, rules)[10].wickets == 0
    assert summarize_innings(balls, [], rules).wickets == 1  # team wicket still counts


def test_partial_over_text_and_economy():
    balls = [ball(1, i, 2, 1) for i in range(1, 6)]
    w = bowling_stats(balls, R)[10]
    assert w.overs == "0.5" and w.economy == 12.0


def test_max_two_overs_per_bowler():
    balls = over(1, [1] * 6, [2] * 6) + over(3, [1] * 6, [2] * 6)
    assert not can_bowl_over(10, 5, balls, R)
    assert can_bowl_over(10, 3, balls, R)  # re-submitting an already-bowled over is not a third over
    assert can_bowl_over(11, 5, balls, R)


# ---------- result ----------
def test_results_chase_defend_tie():
    first = summarize_innings([b for o in range(1, 8) for b in over(o, [1] * 6, [2] * 6)], [], R)
    assert first.runs == 42 and target_for(first) == 43
    won = summarize_innings(over(1, [6] * 6, [1] * 6) + over(2, [6, 6, 1, 1, 1, 1], [1] * 6), [], R, target=43)
    assert won.target_reached
    res = decide_match(first, won, R)
    assert res.winner == "second" and res.margin_type == "wickets" and res.margin == 7
    one_short = [b for o in range(1, 7) for b in over(o, [1] * 6, [2] * 6)] + over(7, [1] * 5 + [2], [2] * 5 + [2])
    short = summarize_innings(one_short, [], R, target=43)
    assert short.runs == 41
    assert decide_match(first, short, R).text == "won by 1 run"
    tied = summarize_innings([b for o in range(1, 8) for b in over(o, [1] * 6, [2] * 6)], [], R)
    assert decide_match(first, tied, R).winner is None


def test_result_requires_finished_innings():
    first = summarize_innings(over(1, [1] * 6, [2] * 6), [], R)
    with pytest.raises(ValueError):
        decide_match(first, first, R)


# ---------- property: replay is deterministic and order-independent ----------
def test_replay_property():
    rng = random.Random(7)
    for _ in range(200):
        balls = []
        for o in range(1, 8):
            bat = [rng.randint(1, 6) for _ in range(6)]
            bowl = [rng.randint(1, 6) for _ in range(6)]
            balls += over(o, bat, bowl)
        pens = [Penalty(runs=rng.randint(-2, 6), after_over=rng.randint(0, 7), after_ball=rng.randint(0, 6))]
        target = rng.choice([None, 30, 45])
        a = summarize_innings(balls, pens, R, target)
        shuffled = balls[:]
        rng.shuffle(shuffled)
        assert summarize_innings(shuffled, pens, R, target) == a  # input order never matters
        assert a.wickets <= R.wickets and a.legal_balls <= R.max_balls
        assert a.runs == a.ball_runs + a.penalty_runs
        # individual stats come from counted balls only and never include penalties
        assert sum(x.runs for x in batting_stats(a.counted_balls).values()) == a.ball_runs
        assert sum(x.runs for x in bowling_stats(a.counted_balls, R).values()) == a.ball_runs
