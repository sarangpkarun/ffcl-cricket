from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RuleSet, Season, User
from app.db.session import get_session
from app.deps import get_current_user, require_admin
from app.schemas import SeasonIn, SeasonOut, SeasonPatch
from app.services.chat import ensure_season_room

router = APIRouter(tags=["seasons"])


@router.post("/seasons", response_model=SeasonOut, status_code=201)
async def create_season(
    body: SeasonIn, _: User = Depends(require_admin), db: AsyncSession = Depends(get_session)
) -> Season:
    rule = await db.scalar(select(RuleSet).where(RuleSet.name == "FFCL").order_by(RuleSet.version.desc()))
    season = Season(**body.model_dump(), rule_set_id=rule.id if rule else None)
    db.add(season)
    try:
        await db.flush()
        await ensure_season_room(db, season)
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(409, "Season name already exists") from e
    return season


@router.get("/seasons", response_model=list[SeasonOut])
async def list_seasons(
    _: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)
) -> list[Season]:
    return list(await db.scalars(select(Season).order_by(Season.id.desc())))


@router.get("/seasons/{season_id}", response_model=SeasonOut)
async def get_season(
    season_id: int, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)
) -> Season:
    season = await db.get(Season, season_id)
    if not season:
        raise HTTPException(404, "Season not found")
    return season


@router.patch("/seasons/{season_id}", response_model=SeasonOut)
async def update_season(
    season_id: int,
    body: SeasonPatch,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> Season:
    season = await db.get(Season, season_id)
    if not season:
        raise HTTPException(404, "Season not found")
    data = body.model_dump(exclude_unset=True)
    if season.status == "archived":
        raise HTTPException(409, "This season is archived. Unarchive it before changing it")
    if data.get("status") == "archived":
        raise HTTPException(409, "Use the archive action to archive a season")
    for k, v in data.items():
        setattr(season, k, v)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(409, "Season name already exists") from e
    return season
