"""Digit parsing and submission validation."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from app.engine.rules import BATTING_PP, BOWLING_PP, RuleConfig

BAT, BOWL = "bat", "bowl"
_KEYCAP = "️⃣"  # variation selector + combining enclosing keycap


@dataclass(frozen=True)
class Violation:
    code: str
    message: str


def parse_digits(raw: str | Sequence[int | str]) -> list[int] | None:
    """Accept '123456', '1 2 3', '1️⃣2️⃣3️⃣', or a list. Returns None if any token is not 0-9."""
    if isinstance(raw, str):
        text = raw.replace(_KEYCAP, "")
        tokens: list[int | str] = [ch for ch in text if not ch.isspace() and ch not in ",-"]
    else:
        tokens = list(raw)
    out: list[int] = []
    for t in tokens:
        try:
            n = int(t)
        except (TypeError, ValueError):
            return None
        if isinstance(t, str) and len(t) != 1:
            return None
        out.append(n)
    return out


def _cap_violations(digits: Sequence[int], rules: RuleConfig) -> list[Violation]:
    counts = sorted(Counter(digits).items(), key=lambda kv: -kv[1])
    out: list[Violation] = []
    for rank, (digit, n) in enumerate(counts):
        limit = rules.max_repeat_one_digit if rank == 0 else rules.max_repeat_other
        if n > limit:
            out.append(
                Violation(
                    "repeat_limit",
                    f"Digit {digit} used {n} times; only one digit may repeat up to "
                    f"{rules.max_repeat_one_digit} times, others up to {rules.max_repeat_other}",
                )
            )
    return out


def _pp_violations(digits: Sequence[int]) -> list[Violation]:
    c = Counter(digits)
    if c[5] != 1 or c[6] != 1:
        return [Violation("pp_requires_5_and_6", "This over needs 5 and 6 exactly once each")]
    return []


def validate_submission(
    role: str, digits: Sequence[int], over_no: int, rules: RuleConfig
) -> list[Violation]:
    """Return all violations (empty list means valid). role is 'bat' or 'bowl'."""
    if role not in (BAT, BOWL):
        raise ValueError(f"unknown role {role!r}")
    if len(digits) != rules.balls_per_over:
        return [
            Violation("invalid_count", f"Need exactly {rules.balls_per_over} digits, got {len(digits)}")
        ]
    bad = [d for d in digits if d < 1 or d > 6]
    if bad:
        return [Violation("invalid_digit", f"Digits must be 1-6, got {sorted(set(bad))}")]

    over_type = rules.over_type(over_no)
    out: list[Violation] = []
    restricted = (role == BAT and over_type == BOWLING_PP) or (role == BOWL and over_type == BATTING_PP)
    if restricted:
        out += _pp_violations(digits)
    if role == BOWL:
        out += _cap_violations(digits, rules)
    return out
