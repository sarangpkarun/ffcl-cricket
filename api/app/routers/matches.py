from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Match, MatchPlayer, RuleSet, Season, Team, TeamMember, User
from app.db.session import get_session
from app.deps import get_current_user, require_admin, user_roles
from app.engine.rules import DEFAULT_RULES
from app.realtime import publish_change
from app.routers.teams import can_manage
from app.schemas import LineupIn, MatchDetail, MatchIn, MatchOut, MatchPatch

router = APIRouter(tags=["matches"])


async def _match(db: AsyncSession, match_id: int) -> Match:
    m = await db.get(Match, match_id)
    if not m:
        raise HTTPException(404, "Match not found")
    return m


async def _check_umpire(db: AsyncSession, umpire_id: int | None, a: int, b: int) -> None:
    if umpire_id is None:
        return
    if "umpire" not in await user_roles(db, umpire_id):
        raise HTTPException(400, "Assigned user does not have the umpire role")
    playing = await db.scalar(
        select(TeamMember.id).where(
            TeamMember.user_id == umpire_id,
            TeamMember.team_id.in_([a, b]),
            TeamMember.status == "approved",
        )
    )
    if playing:
        raise HTTPException(400, "Umpire cannot belong to either team in this match")


@router.post("/seasons/{season_id}/matches", response_model=MatchOut, status_code=201)
async def create_match(
    season_id: int,
    body: MatchIn,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> Match:
    season = await db.get(Season, season_id)
    if not season:
        raise HTTPException(404, "Season not found")
    if body.team_a_id == body.team_b_id:
        raise HTTPException(400, "A team cannot play itself")
    for tid in (body.team_a_id, body.team_b_id):
        team = await db.get(Team, tid)
        if not team or team.season_id != season_id:
            raise HTTPException(400, "Teams must belong to this season")
    await _check_umpire(db, body.umpire_id, body.team_a_id, body.team_b_id)
    rule_set_id = season.rule_set_id
    if rule_set_id is None:
        rs = RuleSet(name="FFCL", version=1, config=DEFAULT_RULES)
        db.add(rs)
        await db.flush()
        rule_set_id = rs.id
    max_no = await db.scalar(
        select(func.coalesce(func.max(Match.match_no), 0)).where(Match.season_id == season_id)
    )
    next_no = (max_no or 0) + 1
    match = Match(
        season_id=season_id, match_no=next_no, rule_set_id=rule_set_id, **body.model_dump()
    )
    db.add(match)
    await db.commit()
    return match


@router.get("/seasons/{season_id}/matches", response_model=list[MatchOut])
async def list_matches(
    season_id: int, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)
) -> list[Match]:
    return list(
        await db.scalars(select(Match).where(Match.season_id == season_id).order_by(Match.match_no))
    )


@router.get("/matches/{match_id}", response_model=MatchDetail)
async def get_match(
    match_id: int, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)
) -> MatchDetail:
    m = await _match(db, match_id)
    lineup = list(
        await db.scalars(
            select(MatchPlayer).where(MatchPlayer.match_id == match_id).order_by(MatchPlayer.id)
        )
    )
    return MatchDetail(**MatchOut.model_validate(m).model_dump(), lineup=lineup)  # type: ignore[arg-type]


@router.patch("/matches/{match_id}", response_model=MatchOut)
async def update_match(
    match_id: int,
    body: MatchPatch,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> Match:
    m = await _match(db, match_id)
    if m.status != "scheduled":
        raise HTTPException(409, "Only scheduled matches can be edited")
    data = body.model_dump(exclude_unset=True)
    if "umpire_id" in data:
        await _check_umpire(db, data["umpire_id"], m.team_a_id, m.team_b_id)
    for k, v in data.items():
        setattr(m, k, v)
    m.seq += 1
    await db.commit()
    await publish_change(m.id, m.seq)
    return m


@router.put("/matches/{match_id}/lineup", response_model=MatchDetail)
async def set_lineup(
    match_id: int,
    body: LineupIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> MatchDetail:
    m = await _match(db, match_id)
    if body.team_id not in (m.team_a_id, m.team_b_id):
        raise HTTPException(400, "Team is not part of this match")
    if m.status not in ("scheduled", "toss"):
        raise HTTPException(409, "Lineup is locked once the match is ready")
    team = await db.get(Team, body.team_id)
    assert team is not None
    if not await can_manage(db, user, team):
        raise HTTPException(403, "Only the captain or an admin can set the lineup")
    ids = body.user_ids
    limit = int(DEFAULT_RULES["players_per_team"])  # type: ignore[call-overload]
    if len(set(ids)) != len(ids):
        raise HTTPException(400, "Duplicate players in lineup")
    if not ids or len(ids) > limit:
        raise HTTPException(400, f"Lineup needs 1 to {limit} players")
    approved = set(
        await db.scalars(
            select(TeamMember.user_id).where(
                TeamMember.team_id == body.team_id, TeamMember.status == "approved"
            )
        )
    )
    if not set(ids) <= approved:
        raise HTTPException(400, "All players must be approved team members")
    users = list(await db.scalars(select(User).where(User.id.in_(ids))))
    bad = [u.name for u in users if u.status != "active" or not u.phone_verified]
    if bad:
        raise HTTPException(
            400, f"Players need an active account and verified phone: {', '.join(bad)}"
        )
    await db.execute(
        delete(MatchPlayer).where(MatchPlayer.match_id == match_id, MatchPlayer.team_id == body.team_id)
    )
    for order, uid in enumerate(ids, start=1):
        db.add(MatchPlayer(match_id=match_id, team_id=body.team_id, user_id=uid, batting_order=order))
    m.seq += 1
    await db.commit()
    await publish_change(m.id, m.seq)
    return await get_match(match_id, user, db)
