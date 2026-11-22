"""The results ledger, the points table and the knockouts.

`sync_ledger` runs inside `recompute()`, so every completion, correction, penalty or withdrawn result
rewrites the ledger in the same transaction. The table is never stored: it is computed from the ledger
(plus point adjustments) every time it is asked for.
"""

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AuditLog,
    Match,
    MatchPlayer,
    MatchResult,
    PointAdjustment,
    RuleSet,
    Season,
    Stage,
    Team,
)
from app.engine.fixtures import Pairing, PlannedMatch, umpire_plan
from app.engine.rules import DEFAULT_RULES, RuleConfig
from app.engine.standings import Adjustment, Outcome, Row, StandingsRules, compute_table
from app.services import match_events
from app.services.announce import say, say_season
from app.services.chat import ensure_match_rooms
from app.services.notify import notify
from app.services.schedule import remove_match, team_members, team_people, umpire_candidates
from app.services.scoring import Recomputed, get_innings, load_rules, recompute

FINISHED = ("completed", "abandoned")


def _when(dt: datetime | None) -> str:
    return dt.astimezone(UTC).strftime("%a %d %b %H:%M UTC") if dt else "a time to be confirmed"


async def season_config(db: AsyncSession, season: Season) -> dict:
    rs = await db.get(RuleSet, season.rule_set_id) if season.rule_set_id else None
    return {**DEFAULT_RULES, **(rs.config if rs else {})}


# ---------- ledger ----------
async def sync_ledger(db: AsyncSession, match: Match, rec: Recomputed | None) -> None:
    """Make the ledger row for this match agree with its result (or remove it if the result is withdrawn)."""
    existing = await db.scalar(select(MatchResult).where(MatchResult.match_id == match.id))
    if not (match.status == "completed" and rec is not None and rec.second is not None):
        if existing is not None and existing.result_type in ("normal", "tie"):
            await db.delete(existing)  # a withdrawn result leaves no trace in the table
        await db.flush()
        await advance_knockouts(db, match)
        return
    i1, i2 = await get_innings(db, match.id)
    by_team = {i1.batting_team_id: rec.first, i2.batting_team_id: rec.second}
    a, b = by_team[match.team_a_id], by_team[match.team_b_id]
    fields = {
        "result_type": "tie" if rec.first.runs == rec.second.runs else "normal",
        "winner_team_id": match.winner_team_id,
        "a_runs": a.runs, "a_balls": a.legal_balls, "a_all_out": a.all_out,
        "b_runs": b.runs, "b_balls": b.legal_balls, "b_all_out": b.all_out,
    }
    if existing is not None:
        for k, v in fields.items():
            setattr(existing, k, v)
    else:
        db.add(MatchResult(match_id=match.id, **fields))
    await db.flush()
    await advance_knockouts(db, match)


async def rebuild_ledger(db: AsyncSession, season_id: int | None = None) -> int:
    """Recompute every completed match from its ball events. A repair tool and a test oracle."""
    q = select(Match).where(Match.status == "completed")
    if season_id is not None:
        q = q.where(Match.season_id == season_id)
    n = 0
    for match in list(await db.scalars(q.order_by(Match.id))):
        await recompute(db, match, await load_rules(db, match))
        n += 1
    return n


# ---------- the table ----------
async def league_matches(db: AsyncSession, season_id: int) -> list[Match]:
    """Matches that count towards the table: the league stage and hand-made matches (no stage)."""
    stage_ids = set(await db.scalars(select(Stage.id).where(Stage.season_id == season_id, Stage.kind != "round_robin")))
    rows = list(await db.scalars(select(Match).where(Match.season_id == season_id)))
    return [m for m in rows if m.stage_id not in stage_ids]


def _row_out(r: Row, teams: dict[int, Team]) -> dict:
    t = teams[r.team]
    return {
        "position": r.position, "team": {"id": t.id, "name": t.name, "color": t.color}, "qualified": r.qualified,
        "played": r.played, "won": r.won, "lost": r.lost, "tied": r.tied, "no_result": r.no_result,
        "points": r.points, "match_points": r.match_points, "adjustments": r.adjustments, "nrr": r.nrr,
        "runs_for": r.runs_for, "balls_for": r.balls_for, "runs_against": r.runs_against,
        "balls_against": r.balls_against, "form": r.form,
    }


async def season_table(db: AsyncSession, season: Season) -> dict:
    cfg = await season_config(db, season)
    rules = StandingsRules.from_config(cfg)
    teams = {t.id: t for t in await db.scalars(select(Team).where(Team.season_id == season.id))}
    matches = {m.id: m for m in await league_matches(db, season.id)}
    ledger = list(await db.scalars(select(MatchResult).where(MatchResult.match_id.in_(matches)))) if matches else []
    outcomes = [
        Outcome(r.match_id, matches[r.match_id].team_a_id, matches[r.match_id].team_b_id, r.result_type, r.winner_team_id,
                r.a_runs, r.a_balls, r.a_all_out, r.b_runs, r.b_balls, r.b_all_out, int(r.decided_at.timestamp() * 1000))
        for r in ledger
    ]
    adjustments = [Adjustment(a.team_id, a.points) for a in await db.scalars(
        select(PointAdjustment).where(PointAdjustment.season_id == season.id, PointAdjustment.voided_at.is_(None)))]
    quota = RuleConfig.from_dict(cfg).max_balls
    rows = compute_table({t.id: t.name for t in teams.values()}, outcomes, adjustments, rules, quota)
    pending = sorted(m.match_no for m in matches.values() if m.status not in FINISHED)
    return {
        "season": {"id": season.id, "name": season.name, "status": season.status,
                   "champion": ({"id": season.champion_team_id, "name": teams[season.champion_team_id].name}
                                if season.champion_team_id in teams else None)},
        "rows": [_row_out(r, teams) for r in rows],
        "qualifiers": rules.qualifiers,
        "points": rules.points,
        "tiebreakers": list(rules.tiebreakers),
        "matches_counted": len(outcomes),
        "league_complete": bool(matches) and not pending,
        "pending_matches": pending,
    }


# ---------- knockouts ----------
async def _final_umpire(db: AsyncSession, season: Season, a: int, b: int, when: datetime | None) -> int | None:
    members = await team_members(db, [a, b])
    plan = umpire_plan([PlannedMatch(Pairing(1, a, b), 0, when or datetime.now(UTC))],
                       await umpire_candidates(db, season.id), members)
    return plan[0]


async def advance_knockouts(db: AsyncSession, match: Match) -> None:
    """When a knockout match changes, make the final (and the champion) follow the semi-final results."""
    if match.stage_id is None:
        return
    stage = await db.get(Stage, match.stage_id)
    if stage is None or stage.kind != "knockout":
        return
    season = await db.get(Season, match.season_id)
    assert season is not None
    matches = list(await db.scalars(select(Match).where(Match.stage_id == stage.id).order_by(Match.id)))
    firsts = sorted((m for m in matches if m.round_label != "Final"), key=lambda m: m.round_label or "")
    final = next((m for m in matches if m.round_label == "Final"), None)
    if int(stage.config.get("qualifiers", 4)) == 4:
        final = await _sync_final(db, season, firsts, final)
    await _sync_champion(db, season, final)


async def _sync_final(db: AsyncSession, season: Season, semis: list[Match], final: Match | None) -> Match | None:
    decided = [m for m in semis if m.status == "completed" and m.winner_team_id]
    if len(decided) == len(semis) == 2:
        w1, w2 = semis[0].winner_team_id, semis[1].winner_team_id
        assert w1 is not None and w2 is not None
        names = {t.id: t.name for t in await db.scalars(select(Team).where(Team.id.in_([w1, w2])))}
        versus = f"{names[w1]} vs {names[w2]}"
        if final is None:
            times = [m.scheduled_at for m in semis if m.scheduled_at]
            when = max(times) + timedelta(days=1) if times else None
            number = (await db.scalar(select(Match.match_no).where(Match.season_id == season.id)
                                      .order_by(Match.match_no.desc()).limit(1))) or 0
            final = Match(season_id=season.id, match_no=number + 1, team_a_id=w1, team_b_id=w2,
                          umpire_id=await _final_umpire(db, season, w1, w2, when), rule_set_id=semis[0].rule_set_id,
                          scheduled_at=when, stage_id=semis[0].stage_id, round_label="Final", published_at=datetime.now(UTC))
            db.add(final)
            await db.flush()
            await ensure_match_rooms(db, final)
            people = await team_people(db, w1) | await team_people(db, w2)
            await notify(db, people, "fixtures_published", "The final is set", f"{versus} (match {final.match_no}) on {_when(when)}.",
                         {"link": f"/matches/{final.id}", "match_id": final.id}, f"final:{final.id}:{w1}:{w2}")
            if final.umpire_id:
                await match_events.umpire_assigned(db, final, final.umpire_id)
            await say_season(db, season, f"🏏 The final is set: {versus}.")
            db.add(AuditLog(actor_id=None, action="knockout.final_created", entity="match", entity_id=final.id,
                            after={"team_a": w1, "team_b": w2}))
        elif (final.team_a_id, final.team_b_id) != (w1, w2):
            if final.status != "scheduled":
                raise HTTPException(409, "This would change a semi-final result after the final has started")
            old = await team_people(db, final.team_a_id) | await team_people(db, final.team_b_id)
            final.team_a_id, final.team_b_id = w1, w2
            await db.execute(delete(MatchPlayer).where(MatchPlayer.match_id == final.id))
            final.seq += 1
            people = old | await team_people(db, w1) | await team_people(db, w2)
            await notify(db, people, "fixture_change", "The final line-up changed", f"{versus} after a correction.",
                         {"link": f"/matches/{final.id}", "match_id": final.id}, f"final-change:{final.id}:{w1}:{w2}")
            await say(db, final, f"🛠 The final line-up changed after a correction: now {versus}.")
            await say_season(db, season, f"🛠 The final is now {versus}.")
            db.add(AuditLog(actor_id=None, action="knockout.final_updated", entity="match", entity_id=final.id,
                            after={"team_a": w1, "team_b": w2}))
        return final
    if final is not None:  # a semi-final result was withdrawn
        if final.status != "scheduled":
            raise HTTPException(409, "A semi-final result cannot be withdrawn once the final has started")
        people = await team_people(db, final.team_a_id) | await team_people(db, final.team_b_id)
        await notify(db, people, "fixture_change", "The final is on hold", "A semi-final result is being corrected.",
                     {"link": "/standings"}, f"final-hold:{final.id}:{datetime.now(UTC).timestamp()}")
        await say_season(db, season, "🛠 The final is on hold until the semi-final result is settled.")
        db.add(AuditLog(actor_id=None, action="knockout.final_removed", entity="match", entity_id=final.id))
        await remove_match(db, final)
        await db.flush()
    return None


async def _sync_champion(db: AsyncSession, season: Season, final: Match | None) -> None:
    champion = final.winner_team_id if final is not None and final.status == "completed" else None
    if season.champion_team_id == champion:
        return
    season.champion_team_id = champion
    if champion is None:
        await say_season(db, season, "🛠 The title decision was withdrawn after a correction.")
        return
    team = await db.get(Team, champion)
    assert team is not None
    await say_season(db, season, f"🏆 {team.name} are the champions of {season.name}!")
    await notify(db, await team_people(db, champion), "result", f"{team.name} are the champions!",
                 f"Congratulations on winning {season.name}.", {"link": "/standings"}, f"champion:{season.id}:{champion}")
