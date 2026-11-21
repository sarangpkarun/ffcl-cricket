"""Rule engine entry point. Implemented in Sprint 2; see RULES.md."""

DEFAULT_RULES = {
    "overs": 7,
    "wickets": 7,
    "balls_per_over": 6,
    "max_overs_per_bowler": 2,
    "players_per_team": 7,
    "normal_over": {"max_repeat_one_digit": 3, "max_repeat_other": 2},
    "bowling_pp_overs": [2],
    "batting_pp_overs": [6],
    "same_digit_is_wicket": True,
    "same_digit_bowler_credit": True,
    "submission_flow": "private_then_reveal",
}
