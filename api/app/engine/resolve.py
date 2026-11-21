"""Ball and over resolution."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.engine.rules import RuleConfig


@dataclass(frozen=True)
class BallResult:
    runs: int
    wicket: bool


def resolve_ball(batter_digit: int, bowler_digit: int, rules: RuleConfig) -> BallResult:
    if rules.same_digit_is_wicket and batter_digit == bowler_digit:
        return BallResult(runs=0, wicket=True)
    return BallResult(runs=batter_digit, wicket=False)


def resolve_over(
    batting: Sequence[int], bowling: Sequence[int], rules: RuleConfig
) -> list[BallResult]:
    if len(batting) != len(bowling):
        raise ValueError("batting and bowling submissions must be the same length")
    return [resolve_ball(b, w, rules) for b, w in zip(batting, bowling, strict=True)]
