"""Match result from two finished innings."""

from dataclasses import dataclass

from app.engine.innings import InningsSummary
from app.engine.rules import RuleConfig


@dataclass(frozen=True)
class MatchResult:
    winner: str | None  # "first" (batted first), "second" (chased), or None for a tie
    margin_type: str  # "runs" | "wickets" | "tie"
    margin: int
    text: str


def target_for(first: InningsSummary) -> int:
    return first.runs + 1


def decide_match(first: InningsSummary, second: InningsSummary, rules: RuleConfig) -> MatchResult:
    """Both innings must be finished. Team names are applied by the caller."""
    if not (first.finished and second.finished):
        raise ValueError("both innings must be finished")
    if second.runs > first.runs:
        wkts = rules.wickets - second.wickets
        return MatchResult("second", "wickets", wkts, f"won by {wkts} wicket{'s' * (wkts != 1)}")
    if second.runs < first.runs:
        diff = first.runs - second.runs
        return MatchResult("first", "runs", diff, f"won by {diff} run{'s' * (diff != 1)}")
    return MatchResult(None, "tie", 0, "match tied")
