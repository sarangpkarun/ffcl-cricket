"""Analytics read models: load the counted balls once, hand them to the pure engine, add names.

Digit habits (which digits a player tends to choose) would help opponents guess digits, so they are only
ever reported from seasons that are finished (completed or archived), never from one still being played.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Match, Season, Team, User
from app.engine.analytics import (
    MatchRecord,
    match_report,
    player_report,
    season_digits,
    season_report,
    team_report,
)
from app.services import stats as stats_svc
from app.services.public import people

FINISHED_SEASON = ("completed", "archived")
FORM_MATCHES = 10


async def team_names(db: AsyncSession, season_ids: set[int]) -> dict[int, dict[str, Any]]:
    if not season_ids:
        return {}
    return {t.id: {"name": t.name, "color": t.color, "season_id": t.season_id}
            for t in await db.scalars(select(Team).where(Team.season_id.in_(season_ids)))}


async def match_analytics(db: AsyncSession, m: Match) -> dict[str, Any]:
    data = await stats_svc.load(db, match_id=m.id, any_result=True)
    rec = data.records.get(m.id)
    names = {i: t["name"] for i, t in (await team_names(db, {m.season_id})).items()}
    if rec is None:
        return {"match_id": m.id, "innings": [], "overs_in_match": 0, "balls_per_over": 6, "biggest_over": None, "over_types": {}}
    return match_report(rec, names)


def _records(data: stats_svc.Loaded) -> list[MatchRecord]:
    return list(data.records.values())


async def season_analytics(db: AsyncSession, season: Season) -> dict[str, Any]:
    data = await stats_svc.load(db, season_id=season.id)
    records = _records(data)
    teams = await team_names(db, {season.id})
    finished = season.status in FINISHED_SEASON
    rows = []
    for tid, t in sorted(teams.items(), key=lambda kv: kv[1]["name"]):
        rep = team_report(tid, records)
        if rep["played"]:
            rows.append({"team": {"id": tid, "name": t["name"], "color": t["color"]}, **rep})
    return {"season": {"id": season.id, "name": season.name, "slug": season.slug, "status": season.status},
            "summary": season_report(records), "teams": rows,
            "digits_available": finished, "digits": season_digits(records) if finished else None}


async def team_analytics(db: AsyncSession, team: Team) -> dict[str, Any]:
    data = await stats_svc.load(db, season_id=team.season_id, team_id=team.id)
    return {"team": {"id": team.id, "name": team.name, "color": team.color}, **team_report(team.id, _records(data))}


async def player_analytics(db: AsyncSession, user: User, season_id: int | None, public: bool = False) -> dict[str, Any]:
    """With `public`, other players appear as the public may see them and those who may not be shown are left out."""
    data = await stats_svc.load(db, season_id=season_id, user_id=user.id)
    records = _records(data)
    seasons = {s.id: s for s in await db.scalars(select(Season).where(Season.id.in_({m.season_id for m in data.matches.values()})))} if records else {}
    finished = [r for r in records if seasons[data.matches[r.match_id].season_id].status in FINISHED_SEASON]
    others: set[int] = set()
    for r in records:
        for i in r.innings:
            others |= {b.bowler_id for b in i.balls if b.batter_id == user.id and b.bowler_id}
            others |= {b.batter_id for b in i.balls if b.bowler_id == user.id and b.batter_id}
    names = await people(db, others) if public else None
    if names is None:
        users = {u.id: u.name for u in await db.scalars(select(User).where(User.id.in_(others)))} if others else {}
        label: dict[int, str] = users
    else:
        label = {uid: p["name"] for uid, p in names.items() if p}
    rep = player_report(user.id, records, names=label, form_matches=FORM_MATCHES)
    if names is not None:  # drop opponents the public may not see, and hide ids of those who chose not to be listed
        for key in ("versus_bowlers", "versus_batters"):
            rep[key] = [{**row, "user_id": (names[row["user_id"]] or {}).get("id")} for row in rep[key] if names.get(row["user_id"])]
    teams = await team_names(db, {m.season_id for m in data.matches.values()})
    for row in rep["form"]:
        row["opponent"] = teams.get(row["opponent_team"], {}).get("name")
        row["team"] = teams.get(row["team"], {}).get("name")
        del row["opponent_team"]
    digits = player_report(user.id, finished, names={}, include_digits=True)["digits"] if finished else None
    return {"player": {"id": user.id, "name": user.name, "player_code": user.player_code},
            "season_id": season_id, **rep, "digits_available": bool(finished), "digits": digits}
