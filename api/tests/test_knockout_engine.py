import pytest

from app.engine.knockout import resolve_tie, round_labels, seed_pairs


def test_four_qualifiers_play_one_v_four_and_two_v_three():
    assert seed_pairs(4) == [(1, 4), (2, 3)] and round_labels(4) == ["Semi-final 1", "Semi-final 2"]


def test_two_qualifiers_go_straight_to_the_final():
    assert seed_pairs(2) == [(1, 2)] and round_labels(2) == ["Final"]


@pytest.mark.parametrize("n", [0, 1, 3, 5, 8])
def test_unsupported_sizes_are_refused(n):
    with pytest.raises(ValueError):
        seed_pairs(n)
    with pytest.raises(ValueError):
        round_labels(n)


def test_a_tie_goes_to_the_higher_league_seed_whichever_side_they_are_listed_on():
    seeds = [30, 10, 20, 40]  # team 30 finished top
    assert resolve_tie(10, 30, seeds) == 30 and resolve_tie(30, 10, seeds) == 30
    assert resolve_tie(20, 40, seeds) == 20 and resolve_tie(40, 20, seeds) == 20


def test_an_unseeded_team_loses_a_tie_and_two_unknowns_default_to_team_a():
    assert resolve_tie(10, 99, [10, 20]) == 10 and resolve_tie(99, 10, [10, 20]) == 10
    assert resolve_tie(98, 99, [10, 20]) == 98
