from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Season, Team, TeamMember, User, UserRole
from app.db.session import get_session
from app.deps import get_current_user, is_admin, require_admin
from app.schemas import MemberIn, MemberOut, TeamDetail, TeamIn, TeamOut, TeamPatch

router = APIRouter(tags=["teams"])
MAX_ROSTER = 7  # TODO(sprint 2): read from the season's rule set


async def _team(db: AsyncSession, team_id: int) -> Team:
    team = await db.get(Team, team_id)
    if not team:
        raise HTTPException(404, "Team not found")
    return team


async def can_manage(db: AsyncSession, user: User, team: Team) -> bool:
    return team.captain_id == user.id or await is_admin(db, user)


async def _approved_count(db: AsyncSession, team_id: int) -> int:
    return (
        await db.scalar(
            select(func.count()).select_from(TeamMember).where(
                TeamMember.team_id == team_id, TeamMember.status == "approved"
            )
        )
    ) or 0


async def _detail(db: AsyncSession, team: Team) -> TeamDetail:
    rows = await db.execute(
        select(TeamMember, User)
        .join(User, User.id == TeamMember.user_id)
        .where(TeamMember.team_id == team.id, TeamMember.status != "removed")
        .order_by(TeamMember.id)
    )
    members = [
        MemberOut(user_id=m.user_id, status=m.status, name=u.name, player_code=u.player_code)
        for m, u in rows
    ]
    return TeamDetail(**TeamOut.model_validate(team).model_dump(), members=members)


@router.post("/seasons/{season_id}/teams", response_model=TeamOut, status_code=201)
async def create_team(
    season_id: int,
    body: TeamIn,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> Team:
    if not await db.get(Season, season_id):
        raise HTTPException(404, "Season not found")
    team = Team(season_id=season_id, **body.model_dump())
    db.add(team)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(409, "Team name already used in this season") from e
    return team


@router.get("/seasons/{season_id}/teams", response_model=list[TeamOut])
async def list_teams(
    season_id: int, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)
) -> list[Team]:
    return list(await db.scalars(select(Team).where(Team.season_id == season_id).order_by(Team.name)))


@router.get("/teams/{team_id}", response_model=TeamDetail)
async def get_team(
    team_id: int, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)
) -> TeamDetail:
    return await _detail(db, await _team(db, team_id))


@router.patch("/teams/{team_id}", response_model=TeamDetail)
async def update_team(
    team_id: int,
    body: TeamPatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> TeamDetail:
    team = await _team(db, team_id)
    data = body.model_dump(exclude_unset=True)
    admin = await is_admin(db, user)
    if not (admin or team.captain_id == user.id):
        raise HTTPException(403, "Not allowed")
    if "captain_id" in data and not admin:
        raise HTTPException(403, "Only an admin can change the captain")
    for field in ("captain_id", "vice_captain_id"):
        uid = data.get(field)
        if uid is not None:
            ok = await db.scalar(
                select(TeamMember.id).where(
                    TeamMember.team_id == team.id,
                    TeamMember.user_id == uid,
                    TeamMember.status == "approved",
                )
            )
            if not ok:
                raise HTTPException(400, f"{field} must be an approved team member")
    for k, v in data.items():
        setattr(team, k, v)
    if data.get("captain_id"):
        has = await db.scalar(
            select(UserRole.id).where(
                UserRole.user_id == data["captain_id"],
                UserRole.role == "captain",
                UserRole.season_id == team.season_id,
            )
        )
        if not has:
            db.add(UserRole(user_id=data["captain_id"], role="captain", season_id=team.season_id))
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(409, "Team name already used in this season") from e
    return await _detail(db, team)


@router.post("/teams/{team_id}/members", response_model=MemberOut, status_code=201)
async def add_member(
    team_id: int,
    body: MemberIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> MemberOut:
    team = await _team(db, team_id)
    manager = await can_manage(db, user, team)
    target_id = body.user_id or user.id
    if target_id != user.id and not manager:
        raise HTTPException(403, "Only the captain or an admin can add other players")
    target = await db.get(User, target_id)
    if not target:
        raise HTTPException(404, "User not found")
    # A player belongs to at most one team per season.
    clash = await db.scalar(
        select(TeamMember.id)
        .join(Team, Team.id == TeamMember.team_id)
        .where(
            Team.season_id == team.season_id,
            TeamMember.user_id == target_id,
            TeamMember.status != "removed",
        )
    )
    if clash:
        raise HTTPException(409, "Player already in a team this season")
    status_ = "approved" if manager else "pending"
    if status_ == "approved" and await _approved_count(db, team_id) >= MAX_ROSTER:
        raise HTTPException(409, f"Roster is full ({MAX_ROSTER})")
    old = await db.scalar(
        select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == target_id)
    )
    if old:  # previously removed
        old.status = status_
        member = old
    else:
        member = TeamMember(team_id=team_id, user_id=target_id, status=status_)
        db.add(member)
    await db.commit()
    return MemberOut(
        user_id=target_id, status=member.status, name=target.name, player_code=target.player_code
    )


@router.post("/teams/{team_id}/members/{user_id}/approve", response_model=MemberOut)
async def approve_member(
    team_id: int,
    user_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> MemberOut:
    team = await _team(db, team_id)
    if not await can_manage(db, user, team):
        raise HTTPException(403, "Not allowed")
    member = await db.scalar(
        select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == user_id)
    )
    if not member or member.status != "pending":
        raise HTTPException(404, "No pending request")
    if await _approved_count(db, team_id) >= MAX_ROSTER:
        raise HTTPException(409, f"Roster is full ({MAX_ROSTER})")
    member.status = "approved"
    await db.commit()
    return MemberOut(user_id=user_id, status="approved")


@router.delete("/teams/{team_id}/members/{user_id}", status_code=204)
async def remove_member(
    team_id: int,
    user_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> None:
    team = await _team(db, team_id)
    if user_id != user.id and not await can_manage(db, user, team):
        raise HTTPException(403, "Not allowed")
    member = await db.scalar(
        select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == user_id)
    )
    if not member or member.status == "removed":
        raise HTTPException(404, "Not a member")
    member.status = "removed"
    if team.captain_id == user_id:
        team.captain_id = None
    if team.vice_captain_id == user_id:
        team.vice_captain_id = None
    await db.commit()
