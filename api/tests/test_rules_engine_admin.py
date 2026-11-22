from app.engine.rules import DEFAULT_RULES
from app.engine.rules_admin import deep_merge, diff, validate


def test_default_rules_are_valid():
    assert validate(DEFAULT_RULES) == []


def test_merge_is_deep_and_does_not_touch_the_original():
    merged = deep_merge(DEFAULT_RULES, {"points": {"win": 3}, "overs": 5, "bowling_pp_overs": [1]})
    assert merged["points"] == {**DEFAULT_RULES["points"], "win": 3}
    assert merged["overs"] == 5 and merged["bowling_pp_overs"] == [1]
    assert DEFAULT_RULES["points"]["win"] == 2 and DEFAULT_RULES["overs"] == 7


def test_diff_lists_only_changes():
    new = deep_merge(DEFAULT_RULES, {"points": {"win": 3}, "overs": 5})
    assert diff(DEFAULT_RULES, new) == [{"path": "overs", "from": 7, "to": 5}, {"path": "points.win", "from": 2, "to": 3}]
    assert diff(DEFAULT_RULES, DEFAULT_RULES) == []
    assert diff({"a": 1}, {"b": 2}) == [{"path": "a", "from": 1, "to": None}, {"path": "b", "from": None, "to": 2}]


def bad(**changes):
    return validate(deep_merge(DEFAULT_RULES, changes))


def test_validation_rejects_nonsense():
    assert any("overs" in e for e in bad(overs=0)) and any("overs" in e for e in bad(overs=99))
    assert any("overs" in e for e in bad(overs="seven"))
    assert any("overs" in e for e in bad(overs=True))
    assert any("exceed" in e for e in bad(overs=1, max_overs_per_bowler=2, bowling_pp_overs=[1], batting_pp_overs=[1]))
    assert any("unknown settings" in e for e in bad(banana=1))
    assert any("points.win" in e for e in bad(points={"win": -1}))
    assert any("tiebreakers" in e for e in bad(tiebreakers=["points", "luck"]))
    assert any("tiebreakers" in e for e in bad(tiebreakers=["points", "points"]))
    assert any("qualifiers" in e for e in bad(knockout={"qualifiers": 3}))
    assert any("bowling_pp_overs" in e for e in bad(bowling_pp_overs=[9]))
    assert any("batting_pp_overs" in e for e in bad(batting_pp_overs="2"))


def test_valid_edits_pass():
    assert bad(points={"win": 3, "tie": 1}, tiebreakers=["points", "wins", "name"], overs=5, bowling_pp_overs=[2],
               batting_pp_overs=[4], knockout={"qualifiers": 2}) == []
