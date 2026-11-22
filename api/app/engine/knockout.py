"""Knockout seeding and tie resolution. Pure functions."""

from collections.abc import Sequence

SUPPORTED_QUALIFIERS = (2, 4)


def seed_pairs(qualifiers: int) -> list[tuple[int, int]]:
    """First-round pairings as (higher seed, lower seed), seeds counted from 1.

    4 qualifiers: 1 v 4 and 2 v 3, the winners meet in the final. 2 qualifiers: straight to the final.
    """
    if qualifiers == 4:
        return [(1, 4), (2, 3)]
    if qualifiers == 2:
        return [(1, 2)]
    raise ValueError(f"knockouts support {SUPPORTED_QUALIFIERS} qualifiers, not {qualifiers}")


def round_labels(qualifiers: int) -> list[str]:
    """Names for the first-round matches, in the same order as seed_pairs."""
    if qualifiers == 4:
        return ["Semi-final 1", "Semi-final 2"]
    if qualifiers == 2:
        return ["Final"]
    raise ValueError(f"knockouts support {SUPPORTED_QUALIFIERS} qualifiers, not {qualifiers}")


def resolve_tie(team_a: int, team_b: int, seeds: Sequence[int]) -> int:
    """A tied knockout is won by the team that finished higher in the league."""
    rank = {t: i for i, t in enumerate(seeds)}
    return team_a if rank.get(team_a, len(seeds)) <= rank.get(team_b, len(seeds)) else team_b
