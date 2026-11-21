"""Rule configuration for the game engine. See RULES.md."""

from dataclasses import dataclass
from typing import Any

DEFAULT_RULES: dict[str, Any] = {
    "overs": 7,
    "wickets": 7,
    "balls_per_over": 6,
    "max_overs_per_bowler": 2,
    "players_per_team": 7,
    # In a "bowling powerplay" over the BATTER is restricted (5 and 6 once each).
    # In a "batting powerplay" over the BOWLER is restricted.
    "bowling_pp_overs": [2],
    "batting_pp_overs": [6],
    "normal_over": {"max_repeat_one_digit": 3, "max_repeat_other": 2},
    "same_digit_is_wicket": True,
    "same_digit_bowler_credit": True,
    "submission_flow": "private_then_reveal",
    "submission_seconds": 180,
}

NORMAL, BOWLING_PP, BATTING_PP = "normal", "bowling_pp", "batting_pp"


@dataclass(frozen=True)
class RuleConfig:
    overs: int = 7
    wickets: int = 7
    balls_per_over: int = 6
    max_overs_per_bowler: int = 2
    players_per_team: int = 7
    bowling_pp_overs: tuple[int, ...] = (2,)
    batting_pp_overs: tuple[int, ...] = (6,)
    max_repeat_one_digit: int = 3
    max_repeat_other: int = 2
    same_digit_is_wicket: bool = True
    same_digit_bowler_credit: bool = True
    submission_seconds: int = 180

    @classmethod
    def from_dict(cls, cfg: dict[str, Any] | None = None) -> "RuleConfig":
        """Build from a stored rule_sets.config; missing keys fall back to defaults."""
        c = {**DEFAULT_RULES, **(cfg or {})}
        normal = {**DEFAULT_RULES["normal_over"], **(c.get("normal_over") or {})}
        return cls(
            overs=c["overs"],
            wickets=c["wickets"],
            balls_per_over=c["balls_per_over"],
            max_overs_per_bowler=c["max_overs_per_bowler"],
            players_per_team=c["players_per_team"],
            bowling_pp_overs=tuple(c["bowling_pp_overs"]),
            batting_pp_overs=tuple(c["batting_pp_overs"]),
            max_repeat_one_digit=normal["max_repeat_one_digit"],
            max_repeat_other=normal["max_repeat_other"],
            same_digit_is_wicket=c["same_digit_is_wicket"],
            same_digit_bowler_credit=c["same_digit_bowler_credit"],
            submission_seconds=c["submission_seconds"],
        )

    @property
    def max_balls(self) -> int:
        return self.overs * self.balls_per_over

    def over_type(self, over_no: int) -> str:
        if over_no in self.bowling_pp_overs:
            return BOWLING_PP
        if over_no in self.batting_pp_overs:
            return BATTING_PP
        return NORMAL
