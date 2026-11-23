"""Archive a season, and the history of past seasons."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Match, Season, Team, User
from app.db.session import get_session
from app.deps import get_current_user, require_admin
from app.engine.leaderboards import leaderboards
from app.services import stats as stats_svc
from app.services.results import FINISHED, season_table

router = APIRouter(tags=["seasons"])


async def _season(db: AsyncSession, season_id: int) -> Season:
    season = await db.get(Season, season_id)
    if not season:
        raise HTTPException(404, "Season not found")
    return season


@router.post("/seasons/{season_id}/archive")
async def archive(season_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)) -> dict:
    """Freeze a finished season. Refused while any match (even an unpublished draft) is unfinished."""
    season = await db.scalar(select(Season).where(Season.id == season_id).with_for_update())
    if not season:
        raise HTTPException(404, "Season not found")
    if season.status == "archived":
        raise HTTPException(409, "This season is already archived")
    open_matches = list(await db.scalars(
        select(Match.match_no).where(Match.season_id == season_id, Match.status.not_in(FINISHED)).order_by(Match.match_no)))
    if open_matches:
        raise HTTPException(409, "Finish, abandon or delete these matches first: " + ", ".join(map(str, open_matches)))
    before = season.status
    season.status, season.archived_at = "archived", datetime.now(UTC)
    db.add(AuditLog(actor_id=admin.id, action="season.archive", entity="season", entity_id=season.id,
                    before={"status": before}, after={"status": "archived"}))
    await db.commit()
    return {"id": season.id, "status": season.status}


@router.post("/seasons/{season_id}/unarchive")
async def unarchive(season_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)) -> dict:
    season = await _season(db, season_id)
    if season.status != "archived":
        raise HTTPException(409, "This season is not archived")
    season.status, season.archived_at = "completed", None
    db.add(AuditLog(actor_id=admin.id, action="season.unarchive", entity="season", entity_id=season.id,
                    before={"status": "archived"}, after={"status": "completed"}))
    await db.commit()
    return {"id": season.id, "status": season.status}


def _top(boards: dict, users: dict, key: str) -> dict | None:
    rows = boards[key]
    if not rows:
        return None
    u = users[rows[0]["user_id"]]
    return {"player": {"id": u.id, "name": u.name, "player_code": u.player_code}, "value": rows[0]["value"], "detail": rows[0]["detail"]}


@router.get("/history")
async def history(_: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> list[dict]:
    """Past seasons (completed or archived), newest first: champion, final table and top performers."""
    return await history_rows(db)


async def history_rows(db: AsyncSession, public_only: bool = False) -> list[dict]:
    q = select(Season).where(Season.status.in_(("completed", "archived"))).order_by(Season.id.desc())
    if public_only:
        q = q.where(Season.is_public.is_(True))
    seasons = list(await db.scalars(q))
    out = []
    for season in seasons:
        table = await season_table(db, season)
        totals, _data = await stats_svc.totals_for(db, season_id=season.id)
        users = await stats_svc.user_names(db, set(totals))
        sr, eco, bpo = await stats_svc.thresholds(db, season)
        boards = leaderboards(totals, {i: u.name for i, u in users.items()}, min_balls_sr=sr, min_balls_economy=eco,
                              balls_per_over=bpo, limit=1)

        out.append({
            "season": {"id": season.id, "name": season.name, "status": season.status, "slug": season.slug},
            "champion": table["season"]["champion"],
            "table": [{"position": r["position"], "team": r["team"]["name"], "played": r["played"], "won": r["won"],
                       "lost": r["lost"], "points": r["points"], "nrr": r["nrr"]} for r in table["rows"]],
            "top_batter": _top(boards, users, "most_runs"), "top_bowler": _top(boards, users, "most_wickets"),
            "most_awards": _top(boards, users, "most_potm"),
            "matches": await db.scalar(select(func.count()).select_from(Match).where(Match.season_id == season.id)),
            "teams": await db.scalar(select(func.count()).select_from(Team).where(Team.season_id == season.id)),
        })
    return out
