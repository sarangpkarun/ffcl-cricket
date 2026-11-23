"""The public, read-only API: what a signed-out visitor may see. See services/public.py for the rules.

These endpoints reuse the same service functions as the signed-in API (so the numbers cannot differ)
and then remove everything private. Responses are cached for a few seconds and rate limited per address.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Match, MatchPlayer, Season, Team, TeamMember, User
from app.db.session import get_session
from app.engine.rules_text import summarize
from app.routers.fixtures import fixture_rows
from app.routers.seasons_admin import history_rows
from app.routers.standings import bracket
from app.routers.stats import player_stats, season_leaderboards, team_stats
from app.services import analytics as analytics_svc
from app.services.live_view import build_live
from app.services.public import (
    cache_headers,
    cached,
    name_of,
    people,
    person_of,
    public_match,
    public_season,
    rate_limit,
    scrub_people,
)
from app.services.results import season_config, season_table

router = APIRouter(prefix="/public", tags=["public"], dependencies=[Depends(rate_limit)])
LIVE_TTL, SHORT, MEDIUM, LONG = 2, 10, 30, 60


def _season_out(s: Season) -> dict:
    return {"id": s.id, "name": s.name, "slug": s.slug, "status": s.status,
            "starts_on": s.starts_on.isoformat() if s.starts_on else None}


async def _fixtures(db: AsyncSession, season_id: int, status: str | None = None, team_id: int | None = None,
                    limit: int | None = None) -> list[dict]:
    rows = await fixture_rows(db, season_id, status, team_id, drafts=False, limit=limit)
    known = await people(db, {r["umpire_id"] for r in rows if r["umpire_id"]})
    out = []
    for r in rows:
        r = {**r, "umpire": name_of(known, r["umpire_id"])}
        for k in ("umpire_id", "published", "stage_id"):
            r.pop(k)
        if r["status"] == "abandoned":
            r["result"] = "Match abandoned"  # the free-text reason stays inside the league
        out.append(r)
    return out


def _ids(value: object) -> set[int]:
    """Every user id in a payload built by the signed-in code ({id, name, player_code} objects)."""
    found: set[int] = set()
    if isinstance(value, list):
        for v in value:
            found |= _ids(v)
    elif isinstance(value, dict):
        if "player_code" in value and "name" in value and isinstance(value.get("id"), int):
            found.add(value["id"])
        for v in value.values():
            found |= _ids(v)
    return found


async def _scrubbed(db: AsyncSession, payload: dict) -> dict:
    return scrub_people(payload, await people(db, _ids(payload)))


async def _leaderboards(db: AsyncSession, season: Season, team_id: int | None, limit: int) -> dict:
    raw = await season_leaderboards(season.id, team_id, limit, None, db)  # type: ignore[arg-type]
    out = await _scrubbed(db, raw)
    for c in out["categories"]:
        if c["key"] != "best_win_pct":  # a player who may not be shown also leaves the ranking
            c["rows"] = [r for r in c["rows"] if r["player"] is not None]
    return out


# ---------- seasons ----------
@router.get("/seasons")
async def seasons(response: Response, db: AsyncSession = Depends(get_session)) -> list[dict]:
    cache_headers(response, MEDIUM)
    rows = list(await db.scalars(select(Season).where(Season.is_public.is_(True), Season.status != "draft").order_by(Season.id.desc())))
    teams = dict((await db.execute(select(Team.season_id, func.count()).group_by(Team.season_id))).all())
    matches = dict((await db.execute(
        select(Match.season_id, func.count()).where(Match.published_at.is_not(None)).group_by(Match.season_id))).all())
    champs = {t.id: t.name for t in await db.scalars(select(Team).where(Team.id.in_({s.champion_team_id for s in rows if s.champion_team_id})))} \
        if any(s.champion_team_id for s in rows) else {}
    return [{**_season_out(s), "teams": teams.get(s.id, 0), "matches": matches.get(s.id, 0),
             "champion": champs.get(s.champion_team_id or 0)} for s in rows]


@router.get("/seasons/{slug}")
async def overview(slug: str, response: Response, db: AsyncSession = Depends(get_session)) -> dict:
    cache_headers(response, SHORT)
    season = await public_season(db, slug)

    async def build() -> dict:
        table = await season_table(db, season)
        board = await _leaderboards(db, season, None, 3)
        cats = {c["key"]: c["rows"] for c in board["categories"]}
        return {
            "season": _season_out(season), "champion": table["season"]["champion"],
            "live": await _fixtures(db, season.id, "live"),
            "next": await _fixtures(db, season.id, "upcoming", limit=5),
            "latest": await _fixtures(db, season.id, "completed", limit=5),
            "table": table["rows"], "qualifiers": table["qualifiers"], "league_complete": table["league_complete"],
            "leaders": {"most_runs": cats["most_runs"][:3], "most_wickets": cats["most_wickets"][:3]},
        }

    return await cached(f"overview:{season.id}", SHORT, build)


@router.get("/seasons/{slug}/fixtures")
async def fixtures(slug: str, response: Response, status: str | None = Query(default=None, pattern="^(upcoming|live|completed)$"),
                   team_id: int | None = None, limit: int = Query(default=200, ge=1, le=200),
                   db: AsyncSession = Depends(get_session)) -> list[dict]:
    cache_headers(response, SHORT)
    season = await public_season(db, slug)
    return await cached(f"fixtures:{season.id}:{status}:{team_id}:{limit}", SHORT,
                        lambda: _fixtures(db, season.id, status, team_id, limit))


@router.get("/seasons/{slug}/standings")
async def standings(slug: str, response: Response, db: AsyncSession = Depends(get_session)) -> dict:
    cache_headers(response, SHORT)
    season = await public_season(db, slug)
    return await cached(f"standings:{season.id}", SHORT, lambda: season_table(db, season))


@router.get("/seasons/{slug}/bracket")
async def season_bracket(slug: str, response: Response, db: AsyncSession = Depends(get_session)) -> dict:
    cache_headers(response, SHORT)
    season = await public_season(db, slug)
    out = await cached(f"bracket:{season.id}", SHORT, lambda: bracket(season.id, None, db))  # type: ignore[arg-type]
    for m in out["matches"]:
        if m["status"] == "abandoned":
            m["result"] = "Match abandoned"
    return out


@router.get("/seasons/{slug}/leaderboards")
async def leaderboards(slug: str, response: Response, team_id: int | None = None,
                       limit: int = Query(default=10, ge=1, le=50), db: AsyncSession = Depends(get_session)) -> dict:
    cache_headers(response, MEDIUM)
    season = await public_season(db, slug)
    return await cached(f"leaders:{season.id}:{team_id}:{limit}", MEDIUM, lambda: _leaderboards(db, season, team_id, limit))


@router.get("/seasons/{slug}/rules")
async def rules(slug: str, response: Response, db: AsyncSession = Depends(get_session)) -> dict:
    cache_headers(response, LONG)
    season = await public_season(db, slug)
    return {"season": _season_out(season), "sections": summarize(await season_config(db, season))}


@router.get("/history")
async def history(response: Response, db: AsyncSession = Depends(get_session)) -> list[dict]:
    cache_headers(response, LONG)

    async def build() -> list[dict]:
        rows = await history_rows(db, public_only=True)
        return [await _scrubbed(db, r) for r in rows]

    return await cached("history", LONG, build)


# ---------- teams and players ----------
@router.get("/teams/{team_id}")
async def team(team_id: int, response: Response, db: AsyncSession = Depends(get_session)) -> dict:
    cache_headers(response, MEDIUM)
    t = await db.get(Team, team_id)
    season = await db.get(Season, t.season_id) if t else None
    if not t or not season or not season.is_public or season.status == "draft":
        raise HTTPException(404, "Team not found")

    async def build() -> dict:
        assert t is not None and season is not None
        stats = await _scrubbed(db, await team_stats(team_id, None, db))  # type: ignore[arg-type]
        rows = list(await db.scalars(select(TeamMember.user_id).where(TeamMember.team_id == team_id, TeamMember.status == "approved")))
        known = await people(db, set(rows))
        members = [{"player": {"id": p["id"], "name": p["name"], "player_code": p["code"]}, "captain": uid == t.captain_id}
                   for uid in rows if (p := known.get(uid))]
        return {"team": {"id": t.id, "name": t.name, "color": t.color}, "season": _season_out(season),
                "members": members, "table": stats["table"], "win_pct": stats["win_pct"], "best": stats["best"],
                "players": stats["players"], "fixtures": await _fixtures(db, season.id, None, team_id)}

    return await cached(f"team:{team_id}", MEDIUM, build)


@router.get("/players/{user_id}")
async def player(user_id: int, response: Response, season: str = Query(min_length=1, max_length=100),
                 db: AsyncSession = Depends(get_session)) -> dict:
    cache_headers(response, MEDIUM)
    s = await public_season(db, season)
    u = await db.get(User, user_id)
    p = person_of(u) if u else None
    if p is None or p["id"] is None:  # unknown, suspended, or chose not to be shown: no page
        raise HTTPException(404, "Player not found")

    async def build() -> dict:
        assert u is not None
        stats = await player_stats(user_id, s.id, None, db)  # type: ignore[arg-type]
        other = list(await db.scalars(
            select(Season).where(Season.is_public.is_(True), Season.status != "draft", Season.id != s.id, Season.id.in_(
                select(distinct(Match.season_id)).join(MatchPlayer, MatchPlayer.match_id == Match.id)
                .where(MatchPlayer.user_id == user_id))).order_by(Season.id.desc())))
        return {"player": {"id": u.id, "name": u.name, "player_code": u.player_code}, "season": _season_out(s),
                "totals": stats["totals"], "history": stats["history"], "other_seasons": [_season_out(o) for o in other]}

    return await cached(f"player:{user_id}:{s.id}", MEDIUM, build)


# ---------- matches ----------
@router.get("/matches/{match_id}")
async def match(match_id: int, response: Response, db: AsyncSession = Depends(get_session)) -> dict:
    cache_headers(response, LIVE_TTL)
    m, season = await public_match(db, match_id)
    return {"season": _season_out(season), "round_label": m.round_label,
            "scheduled_at": m.scheduled_at.isoformat() if m.scheduled_at else None,
            "live": await _live(db, m)}


@router.get("/matches/{match_id}/live")
async def live(match_id: int, response: Response, db: AsyncSession = Depends(get_session)) -> dict:
    cache_headers(response, LIVE_TTL)
    m, _ = await public_match(db, match_id)
    return await _live(db, m)


async def _live(db: AsyncSession, m: Match) -> dict:
    """Keyed by the match's sequence number, so a change is visible at once and a crowd shares one build."""
    out = await cached(f"live:{m.id}:{m.seq}", 5, lambda: build_live(db, m, None))
    return {**out, "you": {"official": False}}


# ---------- analytics ----------
@router.get("/matches/{match_id}/analytics")
async def match_analytics(match_id: int, response: Response, db: AsyncSession = Depends(get_session)) -> dict:
    cache_headers(response, LIVE_TTL)
    m, _ = await public_match(db, match_id)
    return await cached(f"mana:{m.id}:{m.seq}", 5, lambda: analytics_svc.match_analytics(db, m))


@router.get("/seasons/{slug}/analytics")
async def season_analytics(slug: str, response: Response, db: AsyncSession = Depends(get_session)) -> dict:
    cache_headers(response, MEDIUM)
    season = await public_season(db, slug)
    # the season's status is part of the key: digit habits may only ever be served while it is finished, with no cache delay either way
    return await cached(f"sana:{season.id}:{season.status}", MEDIUM, lambda: analytics_svc.season_analytics(db, season))


@router.get("/teams/{team_id}/analytics")
async def team_analytics(team_id: int, response: Response, db: AsyncSession = Depends(get_session)) -> dict:
    cache_headers(response, MEDIUM)
    t = await db.get(Team, team_id)
    season = await db.get(Season, t.season_id) if t else None
    if not t or not season or not season.is_public or season.status == "draft":
        raise HTTPException(404, "Team not found")
    return await cached(f"tana:{team_id}", MEDIUM, lambda: analytics_svc.team_analytics(db, t))


@router.get("/players/{user_id}/analytics")
async def player_analytics(user_id: int, response: Response, season: str = Query(min_length=1, max_length=100),
                           db: AsyncSession = Depends(get_session)) -> dict:
    cache_headers(response, MEDIUM)
    s = await public_season(db, season)
    u = await db.get(User, user_id)
    p = person_of(u) if u else None
    if u is None or p is None or p["id"] is None:
        raise HTTPException(404, "Player not found")

    return await cached(f"pana:{user_id}:{s.id}:{s.status}", MEDIUM, lambda: analytics_svc.player_analytics(db, u, s.id, public=True))


# ---------- sitemap ----------
@router.get("/sitemap")
async def sitemap(response: Response, db: AsyncSession = Depends(get_session)) -> dict:
    cache_headers(response, LONG)
    seasons_ = list(await db.scalars(select(Season).where(Season.is_public.is_(True), Season.status != "draft")))
    slug = {s.id: s.slug for s in seasons_}
    if not slug:
        return {"seasons": [], "teams": [], "matches": [], "players": []}
    teams_ = (await db.execute(select(Team.id, Team.season_id).where(Team.season_id.in_(slug)).limit(20000))).all()
    matches_ = (await db.execute(select(Match.id, Match.season_id).where(
        Match.season_id.in_(slug), Match.published_at.is_not(None)).limit(20000))).all()
    pairs = (await db.execute(
        select(distinct(MatchPlayer.user_id), Match.season_id).join(Match, Match.id == MatchPlayer.match_id)
        .where(Match.season_id.in_(slug), Match.published_at.is_not(None)).limit(20000))).all()
    known = await people(db, {u for u, _ in pairs})
    return {"seasons": [s.slug for s in seasons_],
            "teams": [{"id": i, "season": slug[s]} for i, s in teams_],
            "matches": [{"id": i, "season": slug[s]} for i, s in matches_],
            "players": [{"id": u, "season": slug[s]} for u, s in pairs if (p := known.get(u)) and p["id"] is not None]}
