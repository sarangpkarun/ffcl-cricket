"""Leaderboards, player and team statistics, and player of the match."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Match, MatchAward, MatchPlayer, MatchResult, Season, Team, User
from app.db.session import get_session
from app.deps import get_current_user, is_admin
from app.engine.leaderboards import CATEGORIES, Perf, Totals, aggregate, leaderboards, suggest_potm
from app.services import stats as svc
from app.services.announce import say
from app.services.notify import notify
from app.services.outbox import flush as flush_outbox
from app.services.results import season_table

router = APIRouter(tags=["stats"])


def _who(u: User | None) -> dict | None:
    return {"id": u.id, "name": u.name, "player_code": u.player_code} if u else None


def _totals(t: Totals, bpo: int = 6) -> dict:
    return {
        "matches": t.matches, "innings": t.innings, "runs": t.runs, "balls": t.balls, "fours": t.fours, "sixes": t.sixes,
        "outs": t.outs, "not_outs": t.not_outs, "highest": t.highest, "strike_rate": t.strike_rate, "average": t.average,
        "bowl_innings": t.bowl_innings, "overs": f"{t.bowl_balls // bpo}.{t.bowl_balls % bpo}", "bowl_balls": t.bowl_balls,
        "runs_conceded": t.bowl_runs, "wickets": t.wickets, "economy": t.economy(bpo),
        "best_bowling": f"{t.best_wickets}/{t.best_runs}" if t.best_wickets else None, "potm": t.potm,
    }


async def _season(db: AsyncSession, season_id: int) -> Season:
    season = await db.get(Season, season_id)
    if not season:
        raise HTTPException(404, "Season not found")
    return season


@router.get("/seasons/{season_id}/leaderboards")
async def season_leaderboards(season_id: int, team_id: int | None = None, limit: int = Query(default=10, ge=1, le=50),
                              _: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> dict:
    season = await _season(db, season_id)
    sr, eco, bpo = await svc.thresholds(db, season)
    totals, _data = await svc.totals_for(db, season_id=season_id, team_id=team_id)
    users = await svc.user_names(db, set(totals))
    teams = {t.id: t for t in await db.scalars(select(Team).where(Team.season_id == season_id))}
    boards = leaderboards(totals, {i: u.name for i, u in users.items()}, min_balls_sr=sr, min_balls_economy=eco,
                          balls_per_over=bpo, limit=limit)
    cats = []
    for key, title in CATEGORIES:
        rows = [{"rank": r["rank"], "player": _who(users.get(r["user_id"])),
                 "team": {"id": r["team_id"], "name": teams[r["team_id"]].name} if r["team_id"] in teams else None,
                 "value": r["value"], "detail": r["detail"]} for r in boards[key]]
        cats.append({"key": key, "title": title, "rows": rows})
    table = (await season_table(db, season))["rows"]
    wins = sorted((r for r in table if r["played"] and (team_id is None or r["team"]["id"] == team_id)),
                  key=lambda r: (-(r["won"] + r["tied"] / 2) / r["played"], -r["played"], r["team"]["name"]))[:limit]
    rank, prev = 0, None
    pct_rows = []
    for i, r in enumerate(wins):
        pct = round(100 * (r["won"] + r["tied"] / 2) / r["played"], 1)
        if pct != prev:
            rank, prev = i + 1, pct
        pct_rows.append({"rank": rank, "player": None, "team": {"id": r["team"]["id"], "name": r["team"]["name"]},
                         "value": pct, "detail": f"{r['won']} won of {r['played']}"})
    cats.append({"key": "best_win_pct", "title": "Best win percentage", "rows": pct_rows})
    return {"season": {"id": season.id, "name": season.name}, "team_id": team_id, "categories": cats,
            "minimums": {"strike_rate_balls": sr, "economy_balls": eco}}


@router.get("/players/{user_id}/stats")
async def player_stats(user_id: int, season_id: int | None = None, _: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_session)) -> dict:
    player = await db.get(User, user_id)
    if not player:
        raise HTTPException(404, "Player not found")
    if season_id is not None:
        await _season(db, season_id)
    data = await svc.load(db, season_id=season_id, user_id=user_id)
    mine = [p for p in data.perfs if p.user_id == user_id]
    potm_matches = {mid for mid, uid in data.awards.items() if uid == user_id}
    counts = {user_id: len(potm_matches)}
    total = aggregate(mine, counts).get(user_id) or Totals(user_id)
    seasons = []
    if season_id is None:
        by_season: dict[int, list[Perf]] = {}
        for p in mine:
            by_season.setdefault(data.matches[p.match_id].season_id, []).append(p)
        names = {s.id: s.name for s in await db.scalars(select(Season).where(Season.id.in_(by_season)))} if by_season else {}
        for sid, ps in sorted(by_season.items()):
            c = {user_id: sum(1 for p in ps if p.match_id in potm_matches)}
            seasons.append({"season": {"id": sid, "name": names.get(sid)}, **_totals(aggregate(ps, c)[user_id])})
    team_ids = {t for m in data.matches.values() for t in (m.team_a_id, m.team_b_id)}
    teams = {t.id: t.name for t in await db.scalars(select(Team).where(Team.id.in_(team_ids)))} if team_ids else {}
    results = {r.match_id: r for r in await db.scalars(select(MatchResult).where(MatchResult.match_id.in_(data.matches)))} if mine else {}
    history = []
    for p in sorted(mine, key=lambda x: (x.when, x.match_id), reverse=True):
        m = data.matches[p.match_id]
        other = m.team_b_id if p.team_id == m.team_a_id else m.team_a_id
        winner = results[m.id].winner_team_id
        history.append({
            "match_id": m.id, "match_no": m.match_no, "season_id": m.season_id, "round_label": m.round_label,
            "scheduled_at": m.scheduled_at.isoformat() if m.scheduled_at else None,
            "team": teams.get(p.team_id), "against": teams.get(other), "won": (winner == p.team_id) if winner else None,
            "batted": p.batted, "runs": p.runs, "balls": p.balls, "out": p.outs > 0,
            "bowled": p.bowled, "bowl_balls": p.bowl_balls, "runs_conceded": p.bowl_runs, "wickets": p.wickets,
            "potm": m.id in potm_matches,
        })
    return {"player": _who(player), "season_id": season_id, "totals": _totals(total), "seasons": seasons, "history": history}


@router.get("/teams/{team_id}/stats")
async def team_stats(team_id: int, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> dict:
    team = await db.get(Team, team_id)
    if not team:
        raise HTTPException(404, "Team not found")
    season = await _season(db, team.season_id)
    row = next((r for r in (await season_table(db, season))["rows"] if r["team"]["id"] == team_id), None)
    played = row["played"] if row else 0
    totals, _data = await svc.totals_for(db, season_id=team.season_id, team_id=team_id)
    users = await svc.user_names(db, set(totals))
    sr, eco, bpo = await svc.thresholds(db, season)
    top = leaderboards(totals, {i: u.name for i, u in users.items()}, min_balls_sr=sr, min_balls_economy=eco,
                       balls_per_over=bpo, limit=1)
    best = {k: ({"player": _who(users.get(v[0]["user_id"])), "value": v[0]["value"], "detail": v[0]["detail"]} if v else None)
            for k, v in top.items() if k in ("most_runs", "most_wickets", "highest_score")}
    players = [{"player": _who(users.get(i)), **_totals(t, bpo)} for i, t in sorted(totals.items(), key=lambda kv: (-kv[1].runs, -kv[1].wickets, kv[0]))]
    return {"team": {"id": team.id, "name": team.name}, "table": row,
            "win_pct": round(100 * (row["won"] + row["tied"] / 2) / played, 1) if row and played else None,
            "best": best, "players": players}


# ---------- player of the match ----------
class PotmIn(BaseModel):
    user_id: int


async def _finished(db: AsyncSession, match_id: int) -> tuple[Match, MatchResult | None]:
    m = await db.get(Match, match_id)
    if not m:
        raise HTTPException(404, "Match not found")
    res = await db.scalar(select(MatchResult).where(MatchResult.match_id == match_id))
    return m, res


@router.get("/matches/{match_id}/potm")
async def get_potm(match_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> dict:
    m, res = await _finished(db, match_id)
    if m.published_at is None and not await is_admin(db, user):
        raise HTTPException(404, "Match not found")
    award = await db.scalar(select(MatchAward).where(MatchAward.match_id == match_id, MatchAward.kind == "potm"))
    eligible = res is not None and res.result_type in svc.COUNTED
    official = m.umpire_id == user.id or await is_admin(db, user)
    out: dict = {"eligible": eligible, "can_choose": eligible and official, "award": None, "suggestion": None, "candidates": []}
    names = {}
    if eligible:
        data = await svc.load(db, match_id=match_id)
        names = await svc.user_names(db, {p.user_id for p in data.perfs})
        teams = {t.id: t.name for t in await db.scalars(select(Team).where(Team.id.in_([m.team_a_id, m.team_b_id])))}
        ranked = suggest_potm(data.perfs)
        byid = {p.user_id: p for p in data.perfs}

        def line(uid: int) -> dict:
            p = byid[uid]
            return {"player": _who(names.get(uid)), "team": teams.get(p.team_id), "runs": p.runs, "balls": p.balls,
                    "wickets": p.wickets, "runs_conceded": p.bowl_runs, "score": dict(ranked)[uid]}

        if official:
            out["candidates"] = [line(uid) for uid, _ in ranked]
            out["suggestion"] = out["candidates"][0] if ranked else None
        if award:
            out["award"] = line(award.user_id) if award.user_id in byid else {"player": _who(await db.get(User, award.user_id))}
    elif award:
        out["award"] = {"player": _who(await db.get(User, award.user_id))}
    return out


@router.put("/matches/{match_id}/potm")
async def set_potm(match_id: int, body: PotmIn, user: User = Depends(get_current_user),
                   db: AsyncSession = Depends(get_session)) -> dict:
    m, res = await _finished(db, match_id)
    if m.umpire_id != user.id and not await is_admin(db, user):
        raise HTTPException(403, "Only the match umpire or an admin can choose the player of the match")
    if res is None or res.result_type not in svc.COUNTED:
        raise HTTPException(409, "Player of the match can be chosen once the match has a result")
    in_match = await db.scalar(select(MatchPlayer.id).where(MatchPlayer.match_id == match_id, MatchPlayer.user_id == body.user_id))
    if not in_match:
        raise HTTPException(422, "The player did not play in this match")
    player = await db.get(User, body.user_id)
    assert player is not None
    award = await db.scalar(select(MatchAward).where(MatchAward.match_id == match_id, MatchAward.kind == "potm"))
    before = award.user_id if award else None
    if before == body.user_id:
        return {"user_id": body.user_id, "changed": False}
    if award:
        award.user_id, award.chosen_by = body.user_id, user.id
    else:
        db.add(MatchAward(match_id=match_id, kind="potm", user_id=body.user_id, chosen_by=user.id))
    db.add(AuditLog(actor_id=user.id, action="match.potm", entity="match", entity_id=match_id,
                    before={"user_id": before} if before else None, after={"user_id": body.user_id}))
    await say(db, m, f"⭐ Player of the match: {player.name}.")
    await notify(db, [body.user_id], "award", "Player of the match",
                 f"You are player of the match in match {m.match_no}.", {"link": f"/matches/{m.id}", "match_id": m.id},
                 f"potm:{m.id}:{body.user_id}")
    await db.commit()
    await flush_outbox(db)
    return {"user_id": body.user_id, "changed": True}
