from app.engine.rules import DEFAULT_RULES
from app.engine.rules_admin import deep_merge
from app.engine.rules_text import summarize


def text(cfg=None):
    return "\n".join(i for s in summarize(cfg) for i in s["items"])


def test_default_rules_in_plain_language():
    t = text(DEFAULT_RULES)
    assert "7 overs of 6 balls" in t and "7 wickets" in t and "A win earns 2 points, a tie 1 point and a loss 0 points" in t
    assert "points, then net run rate, then number of wins, then results between the teams concerned, then team name" in t
    assert "over 2" in t and "over 6" in t and "top 4 teams" in t and "loses 1 point" in t
    assert [s["title"] for s in summarize(None)] == ["The match", "How a ball is played", "Over types", "Points and the table", "Knockouts", "Fair play"]


def test_partial_and_changed_rule_sets_are_described_from_what_the_game_uses():
    assert "7 overs" in text({"overs": 7})  # an older, partial rule set still reads fully
    t = text(deep_merge(DEFAULT_RULES, {"points": {"win": 3}, "overs": 5, "knockout": {"qualifiers": 2}, "umpire_duty_penalty": 2}))
    assert "5 overs of 6 balls" in t and "A win earns 3 points" in t and "go through to a final" in t and "loses 2 points" in t
