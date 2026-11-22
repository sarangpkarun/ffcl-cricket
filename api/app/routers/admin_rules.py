"""Rule versions: see them, create a new one from an old one, and apply one to a season."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Match, RuleSet, Season, User
from app.db.session import get_session
from app.deps import require_admin
from app.engine.rules_admin import deep_merge, diff, effective, validate
from app.services.archive import ensure_open

router = APIRouter(tags=["rules"])
NOT_STARTED = ("scheduled", "toss", "ready")


class NewVersionIn(BaseModel):
    from_id: int
    changes: dict = Field(default_factory=dict)
    reason: str = Field(min_length=3, max_length=500)


class ApplyIn(BaseModel):
    rule_set_id: int


async def _rs(db: AsyncSession, rs_id: int) -> RuleSet:
    rs = await db.get(RuleSet, rs_id)
    if not rs:
        raise HTTPException(404, "Rule set not found")
    return rs


async def _previous(db: AsyncSession, rs: RuleSet) -> RuleSet | None:
    return await db.scalar(select(RuleSet).where(RuleSet.name == rs.name, RuleSet.version < rs.version)
                           .order_by(RuleSet.version.desc()).limit(1))


@router.get("/admin/rules")
async def list_rules(_: User = Depends(require_admin), db: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = list(await db.scalars(select(RuleSet).order_by(RuleSet.name, RuleSet.version.desc())))
    seasons = list(await db.scalars(select(Season)))
    counts = dict((await db.execute(select(Match.rule_set_id, func.count()).group_by(Match.rule_set_id))).all())
    return [{"id": r.id, "name": r.name, "version": r.version, "created_at": r.created_at.isoformat(),
             "seasons": [{"id": s.id, "name": s.name} for s in seasons if s.rule_set_id == r.id],
             "matches": counts.get(r.id, 0)} for r in rows]


@router.get("/admin/rules/{rs_id}")
async def get_rules(rs_id: int, _: User = Depends(require_admin), db: AsyncSession = Depends(get_session)) -> dict:
    rs = await _rs(db, rs_id)
    prev = await _previous(db, rs)
    return {"id": rs.id, "name": rs.name, "version": rs.version, "config": effective(rs.config),
            "previous": {"id": prev.id, "version": prev.version} if prev else None,
            "changes": diff(effective(prev.config), effective(rs.config)) if prev else []}


@router.post("/admin/rules", status_code=201)
async def new_version(body: NewVersionIn, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)) -> dict:
    """Copy a version, change some settings, validate, and save it as the next version of that rule set."""
    base = await _rs(db, body.from_id)
    config = deep_merge(effective(base.config), body.changes)
    errors = validate(config)
    if errors:
        raise HTTPException(422, "; ".join(errors))
    changes = diff(effective(base.config), config)
    if not changes:
        raise HTTPException(422, "Nothing changed")
    latest = await db.scalar(select(func.max(RuleSet.version)).where(RuleSet.name == base.name)) or 0
    rs = RuleSet(name=base.name, version=latest + 1, config=config)
    db.add(rs)
    try:
        await db.flush()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(409, "Another version was created at the same time. Try again") from e
    db.add(AuditLog(actor_id=admin.id, action="rules.create", entity="rule_set", entity_id=rs.id, reason=body.reason.strip(),
                    before={"from": base.id, "version": base.version}, after={"version": rs.version, "changes": changes}))
    await db.commit()
    return {"id": rs.id, "name": rs.name, "version": rs.version, "changes": changes}


@router.post("/seasons/{season_id}/rules")
async def apply_rules(season_id: int, body: ApplyIn, admin: User = Depends(require_admin),
                      db: AsyncSession = Depends(get_session)) -> dict:
    """Use a rule version for the table and for matches that have not started. Matches under way or
    finished keep the version they started under."""
    season = await db.scalar(select(Season).where(Season.id == season_id).with_for_update())
    if not season:
        raise HTTPException(404, "Season not found")
    await ensure_open(db, season_id)
    rs = await _rs(db, body.rule_set_id)
    if season.rule_set_id == rs.id:
        raise HTTPException(409, "This season already uses that version")
    before = season.rule_set_id
    season.rule_set_id = rs.id
    unstarted = list(await db.scalars(select(Match).where(
        Match.season_id == season_id, Match.status.in_(NOT_STARTED), Match.rule_set_id != rs.id)))
    for m in unstarted:
        m.rule_set_id = rs.id
        m.seq += 1
    kept = await db.scalar(select(func.count()).select_from(Match).where(
        Match.season_id == season_id, Match.rule_set_id != rs.id, Match.status.not_in(NOT_STARTED)))
    db.add(AuditLog(actor_id=admin.id, action="rules.apply", entity="season", entity_id=season_id,
                    before={"rule_set_id": before}, after={"rule_set_id": rs.id, "repinned": len(unstarted)}))
    await db.commit()
    return {"season_id": season_id, "rule_set_id": rs.id, "version": rs.version, "repinned_matches": len(unstarted),
            "kept_matches": kept or 0}
