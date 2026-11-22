"""Fixture generation: who plays whom, and when. Pure functions, no database.

Round robin uses the circle method: fix one team, rotate the rest, pair opposite positions. With an odd
number of teams a "bye" placeholder joins the circle and whoever meets it sits that round out.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from itertools import pairwise


@dataclass(frozen=True)
class Pairing:
    round_no: int  # 1-based
    home: int  # team id; listed first (team A)
    away: int


def _orient(n: int) -> dict[frozenset[int], tuple[int, int]]:
    """Choose home and away for every pair among teams 0..n-1 so no team is favoured.

    Walk an Euler circuit around the complete graph (adding a dummy team when n is even, so every
    vertex has even degree) and read each edge's direction as home -> away. In a circuit every team
    leaves as often as it is entered, so home and away counts differ by at most one.
    """
    m = n if n % 2 else n + 1
    adj = {u: [v for v in range(m) if v != u] for u in range(m)}
    used: set[frozenset[int]] = set()
    ptr = dict.fromkeys(range(m), 0)
    stack, circuit = [0], []
    while stack:  # Hierholzer's algorithm
        u = stack[-1]
        while ptr[u] < len(adj[u]) and frozenset((u, adj[u][ptr[u]])) in used:
            ptr[u] += 1
        if ptr[u] == len(adj[u]):
            circuit.append(stack.pop())
        else:
            v = adj[u][ptr[u]]
            used.add(frozenset((u, v)))
            stack.append(v)
    circuit.reverse()
    return {frozenset((a, b)): (a, b) for a, b in pairwise(circuit) if a < n and b < n}


def round_robin(team_ids: Sequence[int], legs: int = 1) -> list[Pairing]:
    """Every team meets every other team `legs` times (1 = single, 2 = home and away).

    Order is deterministic. Within a single leg each team's home and away counts differ by at most
    one (see `_orient`); the second leg mirrors the first with home and away swapped.
    """
    ids = list(team_ids)
    if len(ids) != len(set(ids)):
        raise ValueError("a team cannot be entered twice")
    if len(ids) < 2:
        raise ValueError("a round robin needs at least two teams")
    if legs not in (1, 2):
        raise ValueError("legs must be 1 or 2")

    index = {t: i for i, t in enumerate(ids)}
    orient = _orient(len(ids))
    ring: list[int | None] = list(ids)
    if len(ring) % 2:
        ring.append(None)  # the bye
    n = len(ring)
    rounds = n - 1
    first_leg: list[Pairing] = []
    for r in range(rounds):
        for i in range(n // 2):
            a, b = ring[i], ring[n - 1 - i]
            if a is None or b is None:
                continue  # whoever is paired with the bye rests
            h, w = orient[frozenset((index[a], index[b]))]
            first_leg.append(Pairing(r + 1, ids[h], ids[w]))
        ring = [ring[0], ring[-1], *ring[1:-1]]  # rotate everyone except the first
    if legs == 1:
        return first_leg
    second = [Pairing(p.round_no + rounds, p.away, p.home) for p in first_leg]
    return first_leg + second


@dataclass(frozen=True)
class PlannedMatch:
    pairing: Pairing
    slot: int  # index into the generated slot list
    when: datetime


def slot_times(start: date, times: Sequence[time], weekdays: Sequence[int] | None, count: int) -> list[datetime]:
    """The first `count` start times on or after `start`, on the allowed weekdays (0=Monday).

    Times are naive local times; the caller attaches the league's timezone.
    """
    if not times:
        raise ValueError("at least one time of day is needed")
    allowed = set(range(7)) if not weekdays else set(weekdays)
    if not allowed <= set(range(7)):
        raise ValueError("weekdays must be 0-6")
    out: list[datetime] = []
    day = start
    ordered = sorted(set(times))
    while len(out) < count:
        if day.weekday() in allowed:
            out.extend(datetime.combine(day, t) for t in ordered)
        day += timedelta(days=1)
    return out[:count]


def schedule(pairings: Sequence[Pairing], slots: Sequence[datetime], parallel: int = 2, rest_slots: int = 1) -> list[PlannedMatch]:
    """Place matches into slots, round by round.

    - at most `parallel` matches share a slot;
    - a team never plays twice in a slot, and sits out `rest_slots` slots between its matches;
    - a later round never starts before an earlier round's matches have all been placed.
    """
    if parallel < 1 or rest_slots < 0:
        raise ValueError("parallel must be >= 1 and rest_slots >= 0")
    remaining = sorted(pairings, key=lambda p: (p.round_no, p.home, p.away))
    last_played: dict[int, int] = {}
    placed: list[PlannedMatch] = []
    slot = 0
    while remaining:
        if slot >= len(slots):
            raise ValueError("not enough time slots for all the matches")
        current_round = remaining[0].round_no
        chosen: list[Pairing] = []
        busy: set[int] = set()
        for p in remaining:
            if p.round_no != current_round or len(chosen) == parallel:
                break
            ok = all(slot - last_played.get(t, -10**9) > rest_slots and t not in busy for t in (p.home, p.away))
            if ok:
                chosen.append(p)
                busy.update((p.home, p.away))
        for p in chosen:
            remaining.remove(p)
            last_played[p.home] = last_played[p.away] = slot
            placed.append(PlannedMatch(p, slot, slots[slot]))
        slot += 1
    return placed


def umpire_plan(
    matches: Sequence[PlannedMatch],
    candidates: dict[int, int | None],
    team_members: dict[int, set[int]],
) -> dict[int, int | None]:
    """Suggest an umpire for each match (keyed by index into `matches`).

    `candidates` maps umpire user id -> the team that supplies them (None if unaffiliated).
    Rules: never a member of either team in the match; never someone already umpiring or playing
    in the same slot; teams supply umpires evenly (fewest duties first), then the individual with
    the fewest duties. Returns None for a match when nobody qualifies.
    """
    duties_by_user: dict[int, int] = dict.fromkeys(candidates, 0)
    duties_by_team: dict[int | None, int] = {}
    umpiring_in_slot: dict[int, set[int]] = {}
    playing_in_slot: dict[int, set[int]] = {}
    for m in matches:
        playing_in_slot.setdefault(m.slot, set()).update(team_members.get(m.pairing.home, set()) | team_members.get(m.pairing.away, set()))
    out: dict[int, int | None] = {}
    for idx, m in sorted(enumerate(matches), key=lambda x: (x[1].slot, x[0])):
        playing_here = team_members.get(m.pairing.home, set()) | team_members.get(m.pairing.away, set())
        taken = umpiring_in_slot.setdefault(m.slot, set())
        eligible = [
            u for u in candidates
            if u not in playing_here and u not in taken and u not in playing_in_slot.get(m.slot, set())
        ]
        if not eligible:
            out[idx] = None
            continue
        pick = min(eligible, key=lambda u: (duties_by_team.get(candidates[u], 0), duties_by_user[u], u))
        out[idx] = pick
        taken.add(pick)
        duties_by_user[pick] += 1
        duties_by_team[candidates[pick]] = duties_by_team.get(candidates[pick], 0) + 1
    return out
