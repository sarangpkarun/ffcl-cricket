"""CSV exports (admins only). Cells that a spreadsheet could run as a formula are neutralised."""

import csv
import io
import re
from collections.abc import Sequence

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Match, Season, Team, User
from app.db.session import get_session
from app.deps import require_admin
from app.services import stats as stats_svc
from app.services.results import season_table

router = APIRouter(tags=["exports"])


def cell(v: object) -> object:
    """Stop CSV/formula injection: a text cell starting with = + - @ tab or CR gets a leading apostrophe."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return "" if v is None else v


def to_csv(header: list[str], rows: Sequence[Sequence[object]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow([cell(v) for v in r])
    return buf.getvalue()


def _response(name: str, season: Season, body: str) -> Response:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", season.name).strip("-").lower() or "season"
    return Response(body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{slug}-{name}.csv"'})


async def _season(db: AsyncSession, season_id: int) -> Season:
    season = await db.get(Season, season_id)
    if not season:
        raise HTTPException(404, "Season not found")
    return season


@router.get("/seasons/{season_id}/export/fixtures.csv")
async def fixtures_csv(season_id: int, _: User = Depends(require_admin), db: AsyncSession = Depends(get_session)) -> Response:
    season = await _season(db, season_id)
    matches = list(await db.scalars(select(Match).where(Match.season_id == season_id).order_by(Match.match_no)))
    teams = {t.id: t.name for t in await db.scalars(select(Team).where(Team.season_id == season_id))}
    ump = {u.id: u.name for u in await db.scalars(select(User).where(User.id.in_({m.umpire_id for m in matches if m.umpire_id})))} if matches else {}
    rows = [[m.match_no, m.round_label or "", m.scheduled_at.strftime("%Y-%m-%d") if m.scheduled_at else "",
             m.scheduled_at.strftime("%H:%M") if m.scheduled_at else "", teams.get(m.team_a_id), teams.get(m.team_b_id),
             ump.get(m.umpire_id or 0, ""), m.status, "yes" if m.published_at else "no (draft)", m.result_text or ""]
            for m in matches]
    return _response("fixtures", season, to_csv(
        ["match", "round", "date_utc", "time_utc", "team_a", "team_b", "umpire", "status", "published", "result"], rows))


@router.get("/seasons/{season_id}/export/table.csv")
async def table_csv(season_id: int, _: User = Depends(require_admin), db: AsyncSession = Depends(get_session)) -> Response:
    season = await _season(db, season_id)
    t = await season_table(db, season)
    rows = [[r["position"], r["team"]["name"], r["played"], r["won"], r["lost"], r["tied"], r["no_result"], r["points"],
             r["adjustments"], r["nrr"], r["runs_for"], r["balls_for"], r["runs_against"], r["balls_against"]] for r in t["rows"]]
    return _response("table", season, to_csv(
        ["position", "team", "played", "won", "lost", "tied", "no_result", "points", "adjustments", "nrr",
         "runs_for", "balls_for", "runs_against", "balls_against"], rows))


@router.get("/seasons/{season_id}/export/players.csv")
async def players_csv(season_id: int, _: User = Depends(require_admin), db: AsyncSession = Depends(get_session)) -> Response:
    season = await _season(db, season_id)
    totals, _data = await stats_svc.totals_for(db, season_id=season_id)
    users = await stats_svc.user_names(db, set(totals))
    teams = {t.id: t.name for t in await db.scalars(select(Team).where(Team.season_id == season_id))}
    _sr, _eco, bpo = await stats_svc.thresholds(db, season)
    rows = []
    for uid, t in sorted(totals.items(), key=lambda kv: (-kv[1].runs, -kv[1].wickets, users[kv[0]].name)):
        u = users[uid]
        rows.append([u.name, u.player_code, teams.get(t.team_id, ""), t.matches, t.innings, t.runs, t.balls, t.fours, t.sixes,
                     t.strike_rate, t.highest, t.outs, "" if t.average is None else t.average,
                     f"{t.bowl_balls // bpo}.{t.bowl_balls % bpo}", t.bowl_runs, t.wickets, t.economy(bpo),
                     f"{t.best_wickets}/{t.best_runs}" if t.best_wickets else "", t.potm])
    return _response("players", season, to_csv(
        ["player", "code", "team", "matches", "innings", "runs", "balls", "fours", "sixes", "strike_rate", "highest",
         "dismissals", "average", "overs", "runs_conceded", "wickets", "economy", "best_bowling", "player_of_match"], rows))
