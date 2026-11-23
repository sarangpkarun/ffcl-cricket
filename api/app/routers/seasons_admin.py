"""Archive a season, and the history of past seasons."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AuditLog,
    Dispute,
    Match,
    PointAdjustment,
    RosterChange,
    RuleSet,
    Season,
    Team,
    TeamMember,
    UmpireDuty,
    User,
    UserRole,
)
from app.db.session import get_session
from app.deps import get_current_user, require_admin, season_admin
from app.engine.leaderboards import leaderboards
from app.services import stats as stats_svc
from app.services.chat import ensure_season_room
from app.services.results import FINISHED, season_table
from app.services.slugs import unique_slug

router = APIRouter(tags=["seasons"])


async def _season(db: AsyncSession, season_id: int) -> Season:
    season = await db.get(Season, season_id)
    if not season:
        raise HTTPException(404, "Season not found")
    return season


@router.post("/seasons/{season_id}/archive")
async def archive(season_id: int, admin: User = Depends(season_admin("season")), db: AsyncSession = Depends(get_session)) -> dict:
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
async def unarchive(season_id: int, admin: User = Depends(season_admin("season")), db: AsyncSession = Depends(get_session)) -> dict:
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


# ---------- start the next season from this one ----------
class CloneIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    copy_teams: bool = True  # the teams (name, colour, logo), without players
    copy_rosters: bool = False  # also the approved players, captains and vice-captains (implies the teams)


@router.post("/seasons/{season_id}/clone", status_code=201)
async def clone(season_id: int, body: CloneIn, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)) -> dict:
    """A new draft season that uses the same rule version and, if asked, the same teams and players. No matches,
    results, adjustments or champion are copied: it starts empty. Only global admins can create seasons."""
    src = await _season(db, season_id)
    name = body.name.strip()
    if await db.scalar(select(Season.id).where(Season.name == name)):
        raise HTTPException(409, "A season with that name already exists")
    new = Season(name=name, status="draft", rule_set_id=src.rule_set_id, cloned_from_id=src.id, is_public=False,
                 slug=await unique_slug(db, name))
    db.add(new)
    await db.flush()
    await ensure_season_room(db, new)
    teams = players = 0
    if body.copy_teams or body.copy_rosters:
        mapping: dict[int, Team] = {}
        for t in await db.scalars(select(Team).where(Team.season_id == src.id).order_by(Team.id)):
            copy = Team(season_id=new.id, name=t.name, logo_url=t.logo_url, color=t.color)
            db.add(copy)
            mapping[t.id] = copy
            teams += 1
        await db.flush()
        if body.copy_rosters:
            active = set(await db.scalars(select(User.id).where(User.status == "active")))
            for old_id, copy in mapping.items():
                src_team = await db.get(Team, old_id)
                assert src_team is not None
                kept: set[int] = set()
                for m in await db.scalars(select(TeamMember).where(TeamMember.team_id == old_id, TeamMember.status == "approved")):
                    if m.user_id in active:
                        db.add(TeamMember(team_id=copy.id, user_id=m.user_id, status="approved"))
                        kept.add(m.user_id)
                        players += 1
                if src_team.captain_id in kept:
                    copy.captain_id = src_team.captain_id
                    db.add(UserRole(user_id=src_team.captain_id, role="captain", season_id=new.id))
                if src_team.vice_captain_id in kept:
                    copy.vice_captain_id = src_team.vice_captain_id
    db.add(AuditLog(actor_id=admin.id, action="season.clone", entity="season", entity_id=new.id,
                    after={"from": src.id, "teams": teams, "players": players, "rule_set_id": src.rule_set_id}))
    await db.commit()
    return {"id": new.id, "slug": new.slug, "name": new.name, "status": new.status, "teams": teams, "players": players,
            "rule_set_id": new.rule_set_id}


# ---------- one season at a glance ----------
@router.get("/admin/seasons/{season_id}/dashboard")
async def dashboard(season_id: int, _: User = Depends(season_admin("season")), db: AsyncSession = Depends(get_session)) -> dict:
    season = await db.get(Season, season_id)
    if not season:
        raise HTTPException(404, "Season not found")
    by_status = dict((await db.execute(select(Match.status, func.count()).where(
        Match.season_id == season_id, Match.published_at.is_not(None)).group_by(Match.status))).all())
    drafts = await db.scalar(select(func.count()).select_from(Match).where(Match.season_id == season_id, Match.published_at.is_(None)))
    team_ids = select(Team.id).where(Team.season_id == season_id)
    rs = await db.get(RuleSet, season.rule_set_id) if season.rule_set_id else None
    upcoming = list(await db.scalars(select(Match).where(
        Match.season_id == season_id, Match.published_at.is_not(None), Match.status.in_(("scheduled", "toss", "ready")))
        .order_by(Match.scheduled_at.nulls_last(), Match.id).limit(5)))
    names = {t.id: t.name for t in await db.scalars(select(Team).where(Team.season_id == season_id))}
    return {
        "season": {"id": season.id, "name": season.name, "slug": season.slug, "status": season.status, "is_public": season.is_public,
                   "champion": names.get(season.champion_team_id or 0)},
        "rules": {"id": rs.id, "name": rs.name, "version": rs.version} if rs else None,
        "teams": await db.scalar(select(func.count()).select_from(Team).where(Team.season_id == season_id)),
        "players": await db.scalar(select(func.count()).select_from(TeamMember).where(TeamMember.team_id.in_(team_ids), TeamMember.status == "approved")),
        "matches": {"drafts": drafts or 0, "upcoming": sum(by_status.get(k, 0) for k in ("scheduled", "toss", "ready")),
                    "live": sum(by_status.get(k, 0) for k in ("innings1", "break", "innings2")),
                    "finished": sum(by_status.get(k, 0) for k in ("completed", "abandoned"))},
        "next": [{"id": m.id, "match_no": m.match_no, "teams": f"{names.get(m.team_a_id)} vs {names.get(m.team_b_id)}",
                  "scheduled_at": m.scheduled_at.isoformat() if m.scheduled_at else None} for m in upcoming],
        "waiting": {
            "roster_changes": await db.scalar(select(func.count()).select_from(RosterChange).where(RosterChange.status == "pending", RosterChange.team_id.in_(team_ids))),
            "disputes": await db.scalar(select(func.count()).select_from(Dispute).where(Dispute.season_id == season_id, Dispute.status.in_(("open", "in_review")))),
            "missed_duties": await db.scalar(select(func.count()).select_from(UmpireDuty).join(Match, Match.id == UmpireDuty.match_id).where(
                Match.season_id == season_id, UmpireDuty.status == "missed")),
        },
        "adjustments": await db.scalar(select(func.count()).select_from(PointAdjustment).where(PointAdjustment.season_id == season_id, PointAdjustment.voided_at.is_(None))),
    }
