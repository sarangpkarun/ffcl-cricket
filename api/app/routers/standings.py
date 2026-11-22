"""The points table, the knockout bracket, and the admin tools that feed them."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Match, Season, Stage, Team, User
from app.db.session import get_session
from app.deps import get_current_user, require_admin
from app.engine.fixtures import Pairing, PlannedMatch, umpire_plan
from app.engine.knockout import SUPPORTED_QUALIFIERS, round_labels, seed_pairs
from app.realtime import publish_change
from app.services import match_events
from app.services.announce import say_season
from app.services.chat import ensure_match_rooms
from app.services.duties import sync_duty
from app.services.notify import notify
from app.services.outbox import flush as flush_outbox
from app.services.results import rebuild_ledger, season_config, season_table
from app.services.schedule import team_members, team_people, umpire_candidates

router = APIRouter(tags=["standings"])


async def _season(db: AsyncSession, season_id: int) -> Season:
    season = await db.get(Season, season_id)
    if not season:
        raise HTTPException(404, "Season not found")
    return season


def _when(dt: datetime | None) -> str:
    return dt.astimezone(UTC).strftime("%a %d %b %H:%M UTC") if dt else "a time to be confirmed"


@router.get("/seasons/{season_id}/standings")
async def standings(season_id: int, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> dict:
    return await season_table(db, await _season(db, season_id))


async def _stage(db: AsyncSession, season_id: int) -> Stage | None:
    return await db.scalar(select(Stage).where(Stage.season_id == season_id, Stage.kind == "knockout"))


@router.get("/seasons/{season_id}/bracket")
async def bracket(season_id: int, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)) -> dict:
    season = await _season(db, season_id)
    stage = await _stage(db, season_id)
    teams = {t.id: t for t in await db.scalars(select(Team).where(Team.season_id == season_id))}
    champion = teams.get(season.champion_team_id or 0)
    if stage is None:
        return {"stage": None, "matches": [], "champion": {"id": champion.id, "name": champion.name} if champion else None}
    matches = list(await db.scalars(select(Match).where(Match.stage_id == stage.id).order_by(Match.id)))
    order = {"Semi-final 1": 0, "Semi-final 2": 1, "Final": 2}
    matches.sort(key=lambda m: order.get(m.round_label or "", 9))

    def side(tid: int) -> dict:
        return {"id": tid, "name": teams[tid].name, "color": teams[tid].color}

    return {
        "stage": {"id": stage.id, "name": stage.name, "qualifiers": stage.config.get("qualifiers"),
                  "seeds": [{"seed": i + 1, "team": side(t)} for i, t in enumerate(stage.config.get("seeds", [])) if t in teams]},
        "matches": [{"id": m.id, "match_no": m.match_no, "round_label": m.round_label, "status": m.status,
                     "scheduled_at": m.scheduled_at.isoformat() if m.scheduled_at else None,
                     "team_a": side(m.team_a_id), "team_b": side(m.team_b_id),
                     "result": m.result_text, "winner_team_id": m.winner_team_id} for m in matches],
        "champion": {"id": champion.id, "name": champion.name} if champion else None,
    }


class KnockoutIn(BaseModel):
    first_at: datetime  # kick-off of the first semi-final (or the final when only two qualify)
    second_at: datetime | None = None  # second semi-final; defaults to the same time
    allow_incomplete: bool = False  # start the knockouts even though league matches are unfinished


@router.post("/seasons/{season_id}/knockouts/generate", status_code=201)
async def generate_knockouts(season_id: int, body: KnockoutIn, admin: User = Depends(require_admin),
                             db: AsyncSession = Depends(get_session)) -> dict:
    """Seed the top teams from the table into the semi-finals (or straight into the final)."""
    season = await _season(db, season_id)
    if await _stage(db, season_id):
        raise HTTPException(409, "This season already has knockouts")
    table = await season_table(db, season)
    cfg = await season_config(db, season)
    qualifiers = int(table["qualifiers"])
    if qualifiers not in SUPPORTED_QUALIFIERS:
        raise HTTPException(422, f"Knockouts support {SUPPORTED_QUALIFIERS} qualifiers")
    if not table["league_complete"] and not body.allow_incomplete:
        pending = ", ".join(map(str, table["pending_matches"])) or "none played yet"
        raise HTTPException(409, f"League matches are still to be finished (matches: {pending})")
    if len(table["rows"]) < qualifiers:
        raise HTTPException(422, f"At least {qualifiers} teams are needed")
    seeds = [r["team"]["id"] for r in table["rows"][:qualifiers]]
    pairs = seed_pairs(qualifiers)
    labels = round_labels(qualifiers)
    times = [body.first_at, body.second_at or body.first_at][: len(pairs)]

    next_ord = (await db.scalar(select(func.coalesce(func.max(Stage.ord), 0)).where(Stage.season_id == season_id)) or 0) + 1
    stage = Stage(season_id=season_id, kind="knockout", name="Knockouts", ord=next_ord,
                  config={"qualifiers": qualifiers, "tie": (cfg.get("knockout") or {}).get("tie", "higher_seed"), "seeds": seeds})
    db.add(stage)
    await db.flush()
    members = await team_members(db, seeds)
    planned = [PlannedMatch(Pairing(1, seeds[hi - 1], seeds[lo - 1]), 0 if times[i] == times[0] else 1, times[i])
               for i, (hi, lo) in enumerate(pairs)]
    umpires = umpire_plan(planned, await umpire_candidates(db, season_id), members)
    number = await db.scalar(select(func.coalesce(func.max(Match.match_no), 0)).where(Match.season_id == season_id)) or 0
    base = (await db.scalars(select(Match.rule_set_id).where(Match.season_id == season_id).limit(1))).first() or season.rule_set_id
    if base is None:
        raise HTTPException(409, "The season has no matches or rule set yet")
    now = datetime.now(UTC)
    created: list[Match] = []
    for i, (pm, label) in enumerate(zip(planned, labels, strict=True)):
        number += 1
        m = Match(season_id=season_id, match_no=number, team_a_id=pm.pairing.home, team_b_id=pm.pairing.away,
                  umpire_id=umpires[i], rule_set_id=base, scheduled_at=pm.when, stage_id=stage.id,
                  round_label=label, published_at=now)
        db.add(m)
        await db.flush()
        await ensure_match_rooms(db, m)
        await sync_duty(db, m)
        created.append(m)
    names = {t.id: t.name for t in await db.scalars(select(Team).where(Team.id.in_(seeds)))}
    for m in created:
        for team_id, opp in ((m.team_a_id, m.team_b_id), (m.team_b_id, m.team_a_id)):
            await notify(db, await team_people(db, team_id), "fixtures_published", "The knockouts are set",
                         f"{names[team_id]} play {names[opp]} on {_when(m.scheduled_at)} ({m.round_label}).",
                         {"link": f"/matches/{m.id}", "match_id": m.id}, f"ko:{stage.id}:{m.id}")
        if m.umpire_id:
            await match_events.umpire_assigned(db, m, m.umpire_id)
    lines = ", ".join(f"{m.round_label}: {names[m.team_a_id]} v {names[m.team_b_id]}" for m in created)
    await say_season(db, season, f"🏆 The knockouts are set. {lines}.")
    db.add(AuditLog(actor_id=admin.id, action="knockouts.generate", entity="season", entity_id=season_id,
                    after={"seeds": seeds, "matches": [m.id for m in created], "incomplete": not table["league_complete"]}))
    await db.commit()
    for m in created:
        await publish_change(m.id, m.seq)
    await flush_outbox(db)
    return {"stage_id": stage.id, "seeds": seeds, "matches": [{"id": m.id, "round_label": m.round_label} for m in created]}


class RebuildIn(BaseModel):
    season_id: int | None = None


@router.post("/admin/results/rebuild")
async def rebuild(body: RebuildIn, _: User = Depends(require_admin), db: AsyncSession = Depends(get_session)) -> dict:
    """Recompute every completed match from its ball events and rewrite the ledger. Safe to repeat."""
    n = await rebuild_ledger(db, body.season_id)
    await db.commit()
    await flush_outbox(db)
    return {"rebuilt": n}
