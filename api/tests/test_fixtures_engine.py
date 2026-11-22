import random
from collections import Counter, defaultdict
from datetime import date, time
from itertools import pairwise

import pytest

from app.engine.fixtures import (
    Pairing,
    PlannedMatch,
    round_robin,
    schedule,
    slot_times,
    umpire_plan,
)


# ---------- round robin ----------
def test_four_teams_match_the_hand_worked_circle_method():
    ps = round_robin([1, 2, 3, 4])
    by_round = defaultdict(set)
    for p in ps:
        by_round[p.round_no].add(frozenset((p.home, p.away)))
    assert dict(by_round) == {
        1: {frozenset({1, 4}), frozenset({2, 3})},
        2: {frozenset({1, 3}), frozenset({2, 4})},
        3: {frozenset({1, 2}), frozenset({3, 4})},
    }


@pytest.mark.parametrize("n", range(2, 14))
def test_every_pair_meets_exactly_once(n):
    ids = list(range(100, 100 + n))
    ps = round_robin(ids)
    pairs = [frozenset((p.home, p.away)) for p in ps]
    assert len(ps) == n * (n - 1) // 2 and len(set(pairs)) == len(pairs)
    assert all(p.home != p.away and {p.home, p.away} <= set(ids) for p in ps)


@pytest.mark.parametrize("n", range(2, 14))
def test_no_team_plays_twice_in_a_round_and_round_sizes_are_right(n):
    ps = round_robin(list(range(n)))
    rounds = defaultdict(list)
    for p in ps:
        rounds[p.round_no].append(p)
    assert sorted(rounds) == list(range(1, (n - 1 if n % 2 == 0 else n) + 1))
    for matches in rounds.values():
        teams = [t for m in matches for t in (m.home, m.away)]
        assert len(teams) == len(set(teams))
        assert len(matches) == n // 2


@pytest.mark.parametrize("n", [3, 5, 7, 9])
def test_odd_number_of_teams_each_team_sits_out_exactly_once(n):
    ps = round_robin(list(range(n)))
    rounds = {p.round_no for p in ps}
    for t in range(n):
        played = {p.round_no for p in ps if t in (p.home, p.away)}
        assert len(rounds - played) == 1


@pytest.mark.parametrize("n", range(2, 14))
def test_home_and_away_are_balanced_in_a_single_leg(n):
    ps = round_robin(list(range(n)))
    home, away = Counter(p.home for p in ps), Counter(p.away for p in ps)
    assert all(abs(home[t] - away[t]) <= 1 for t in range(n))


@pytest.mark.parametrize("n", range(2, 11))
def test_double_round_robin_mirrors_with_home_and_away_swapped(n):
    ids = list(range(n))
    single, double = round_robin(ids, 1), round_robin(ids, 2)
    assert len(double) == 2 * len(single)
    ordered = Counter((p.home, p.away) for p in double)
    assert all(v == 1 for v in ordered.values()) and len(ordered) == n * (n - 1)  # each ordered pair once
    rounds = max(p.round_no for p in single)
    for first, second in zip(double[: len(single)], double[len(single):], strict=True):
        assert (second.home, second.away, second.round_no) == (first.away, first.home, first.round_no + rounds)
    home, away = Counter(p.home for p in double), Counter(p.away for p in double)
    assert all(home[t] == away[t] == n - 1 for t in ids)  # perfectly balanced over two legs


def test_generation_is_deterministic():
    assert round_robin([5, 3, 9, 1, 7], 2) == round_robin([5, 3, 9, 1, 7], 2)


@pytest.mark.parametrize("bad", [[], [1], [1, 1, 2]])
def test_invalid_team_lists_are_rejected(bad):
    with pytest.raises(ValueError):
        round_robin(bad)


def test_invalid_legs_rejected():
    with pytest.raises(ValueError):
        round_robin([1, 2, 3], 3)


# ---------- time slots ----------
def test_slots_start_on_or_after_the_start_date_in_order():
    s = slot_times(date(2030, 1, 7), [time(20, 30), time(19, 0)], None, 5)  # a Monday
    assert [x.isoformat() for x in s] == [
        "2030-01-07T19:00:00", "2030-01-07T20:30:00", "2030-01-08T19:00:00", "2030-01-08T20:30:00", "2030-01-09T19:00:00"]


def test_slots_respect_allowed_weekdays():
    s = slot_times(date(2030, 1, 7), [time(18, 0)], [5, 6], 4)  # Saturdays and Sundays only
    assert [x.date().isoformat() for x in s] == ["2030-01-12", "2030-01-13", "2030-01-19", "2030-01-20"]
    assert all(x.weekday() in (5, 6) for x in s)


@pytest.mark.parametrize("args", [([], None, 3), ([time(9)], [7], 3)])
def test_bad_slot_inputs_rejected(args):
    with pytest.raises(ValueError):
        slot_times(date(2030, 1, 1), *args)


# ---------- scheduling ----------
def run_schedule(n, legs, parallel, rest):
    ps = round_robin(list(range(n)), legs)
    slots = slot_times(date(2030, 1, 1), [time(9), time(11), time(13), time(15)], None, len(ps) * (rest + 1) + 20)
    return ps, schedule(ps, slots, parallel=parallel, rest_slots=rest)


@pytest.mark.parametrize("n", [2, 3, 4, 5, 6, 8, 9])
@pytest.mark.parametrize("legs", [1, 2])
@pytest.mark.parametrize("parallel", [1, 2, 3])
@pytest.mark.parametrize("rest", [0, 1, 2])
def test_schedule_obeys_every_constraint(n, legs, parallel, rest):
    ps, placed = run_schedule(n, legs, parallel, rest)
    assert len(placed) == len(ps) and {m.pairing for m in placed} == set(ps)  # nothing lost or duplicated
    per_slot = defaultdict(list)
    for m in placed:
        per_slot[m.slot].append(m)
    for ms in per_slot.values():
        assert len(ms) <= parallel
        teams = [t for m in ms for t in (m.pairing.home, m.pairing.away)]
        assert len(teams) == len(set(teams))  # nobody twice in one slot
    for t in range(n):
        slots = sorted(m.slot for m in placed if t in (m.pairing.home, m.pairing.away))
        assert all(b - a > rest for a, b in pairwise(slots))  # rest between matches
    by_round = defaultdict(list)
    for m in placed:
        by_round[m.pairing.round_no].append(m.slot)
    rounds = sorted(by_round)
    assert all(max(by_round[a]) < min(by_round[b]) for a, b in pairwise(rounds))  # rounds stay in order


def test_schedule_times_match_their_slots():
    ps = round_robin([1, 2, 3, 4])
    slots = slot_times(date(2030, 1, 1), [time(19, 0)], None, 40)
    placed = schedule(ps, slots, parallel=1, rest_slots=0)
    assert all(m.when == slots[m.slot] for m in placed) and [m.slot for m in placed] == sorted(m.slot for m in placed)


def test_schedule_runs_out_of_slots_loudly():
    with pytest.raises(ValueError, match="slots"):
        schedule(round_robin([1, 2, 3, 4]), slot_times(date(2030, 1, 1), [time(9)], None, 2), parallel=1)


@pytest.mark.parametrize("kw", [{"parallel": 0}, {"rest_slots": -1}])
def test_schedule_rejects_bad_settings(kw):
    with pytest.raises(ValueError):
        schedule([Pairing(1, 1, 2)], slot_times(date(2030, 1, 1), [time(9)], None, 5), **kw)


# ---------- umpires ----------
def plan_for(n_teams, candidates, parallel=1, members=None):
    ids = list(range(1, n_teams + 1))
    ps = round_robin(ids)
    slots = slot_times(date(2030, 1, 1), [time(9), time(11)], None, 200)
    placed = schedule(ps, slots, parallel=parallel, rest_slots=0)
    members = members if members is not None else {t: {t * 100 + i for i in range(3)} for t in ids}
    return placed, umpire_plan(placed, candidates, members), members


def test_umpires_are_never_in_either_team_or_double_booked():
    # umpires 1..4 come from the playing teams; 900-901 are neutral
    members = {t: {t * 100, t * 100 + 1} for t in range(1, 5)}
    candidates = {100: 1, 200: 2, 300: 3, 400: 4, 900: None, 901: None}
    placed, plan, _ = plan_for(4, candidates, parallel=2, members=members)
    in_slot = defaultdict(set)
    for idx, m in enumerate(placed):
        u = plan[idx]
        assert u is not None
        assert u not in members[m.pairing.home] | members[m.pairing.away]
        playing_now = {x for q in placed if q.slot == m.slot for t in (q.pairing.home, q.pairing.away) for x in members[t]}
        assert u not in playing_now  # not playing elsewhere at the same time
        assert u not in in_slot[m.slot]  # not umpiring two matches at once
        in_slot[m.slot].add(u)


def test_umpire_duties_are_shared_evenly():
    candidates = {1001: 11, 1002: 12, 1003: 13, 1004: 14}  # four neutral teams each supply one umpire
    _placed, plan, _ = plan_for(6, candidates, parallel=1)
    counts = Counter(plan.values())
    assert None not in counts and max(counts.values()) - min(counts.values()) <= 1
    teams = Counter(candidates[u] for u in plan.values())
    assert max(teams.values()) - min(teams.values()) <= 1


def test_a_team_supplying_more_umpires_does_not_take_more_duties():
    candidates = {1: 11, 2: 11, 3: 11, 4: 12}  # team 11 offers three people, team 12 only one
    _placed, plan, _ = plan_for(5, candidates, parallel=1)
    teams = Counter(candidates[u] for u in plan.values() if u)
    assert abs(teams[11] - teams[12]) <= 1


def test_no_candidates_means_no_umpire_not_a_crash():
    placed, plan, _ = plan_for(4, {})
    assert set(plan.values()) == {None} and len(plan) == len(placed)


def test_everyone_busy_leaves_a_match_without_an_umpire():
    # one umpire, two matches at the same time: the second has nobody
    ps = [Pairing(1, 1, 2), Pairing(1, 3, 4)]
    placed = schedule(ps, slot_times(date(2030, 1, 1), [time(9)], None, 4), parallel=2, rest_slots=0)
    members = {1: {11}, 2: {12}, 3: {13}, 4: {14}}
    plan = umpire_plan(placed, {900: None}, members)
    assert sorted(v is None for v in plan.values()) == [False, True]


def test_umpire_plan_is_deterministic_and_random_inputs_never_break_the_rules():
    rng = random.Random(3)
    for _ in range(40):
        n = rng.randint(3, 8)
        ids = list(range(1, n + 1))
        members = {t: {t * 100 + i for i in range(rng.randint(1, 4))} for t in ids}
        pool = [u for t in members for u in members[t]] + list(range(900, 900 + rng.randint(0, 3)))
        candidates = {u: next((t for t in ids if u in members[t]), None) for u in rng.sample(pool, min(len(pool), rng.randint(0, 8)))}
        ps = round_robin(ids, rng.choice([1, 2]))
        placed = schedule(ps, slot_times(date(2030, 1, 1), [time(9), time(12)], None, 400), parallel=rng.randint(1, 3), rest_slots=rng.randint(0, 1))
        plan = umpire_plan(placed, candidates, members)
        assert plan == umpire_plan(placed, candidates, members)
        by_slot = defaultdict(list)
        for idx, m in enumerate(placed):
            u = plan[idx]
            if u is None:
                continue
            assert u not in members[m.pairing.home] | members[m.pairing.away]
            by_slot[m.slot].append(u)
        assert all(len(v) == len(set(v)) for v in by_slot.values())
    _ = PlannedMatch
