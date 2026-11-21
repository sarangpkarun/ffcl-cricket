"""Runs every worked example from RULES.md (via fixtures/rules_examples.json)."""

import json
from pathlib import Path

import pytest

from app.engine import BAT, BOWL, RuleConfig, resolve_ball, resolve_over, validate_submission

EX = json.loads((Path(__file__).parent / "fixtures" / "rules_examples.json").read_text())
RULES = RuleConfig()


def check(role, case):
    v = validate_submission(role, case["digits"], case["over"], RULES)
    assert (not v) == case["valid"], f"{case['id']}: {v}"
    if not case["valid"]:
        assert case["code"] in {x.code for x in v}, f"{case['id']}: {v}"


@pytest.mark.parametrize("case", EX["bowling_normal"], ids=lambda c: c["id"])
def test_bowling_normal(case):
    check(BOWL, case)


@pytest.mark.parametrize("case", EX["batting_pp_over2"], ids=lambda c: c["id"])
def test_batter_restricted_in_over_2(case):
    check(BAT, case)


@pytest.mark.parametrize("case", EX["bowling_pp_over6"], ids=lambda c: c["id"])
def test_bowler_restricted_in_over_6(case):
    check(BOWL, case)


@pytest.mark.parametrize("case", EX["batting_normal"], ids=lambda c: c["id"])
def test_batting_normal(case):
    check(BAT, case)


@pytest.mark.parametrize("case", EX["balls"], ids=lambda c: c["id"])
def test_ball_outcomes(case):
    r = resolve_ball(case["batter"], case["bowler"], RULES)
    assert (r.runs, r.wicket) == (case["runs"], case["wicket"])


@pytest.mark.parametrize("case", EX["overs"], ids=lambda c: c["id"])
def test_over_totals(case):
    res = resolve_over(case["batting"], case["bowling"], RULES)
    assert sum(r.runs for r in res) == case["runs"]
    assert sum(r.wicket for r in res) == case["wickets"]


def test_bowler_cap_does_not_apply_to_batter_in_normal_over():
    assert validate_submission(BAT, [1, 1, 1, 1, 1, 1], 1, RULES) == []


def test_bowler_free_digits_also_capped_in_over_2_normal_rule():
    assert validate_submission(BOWL, [1, 1, 1, 1, 2, 3], 2, RULES)
