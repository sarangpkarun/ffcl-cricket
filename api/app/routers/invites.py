"""Invites: an admin imports a CSV of players and hands out one-time links; the player opens theirs and sets a password."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password_async
from app.db.models import AuditLog, Invite, Season, Team, TeamMember, User, UserRole
from app.db.session import get_session
from app.deps import season_admin
from app.routers.auth import _issue, client_ip, throttle
from app.schemas import TokenOut
from app.services import invites as svc
from app.services.approvals import tell
from app.services.archive import ensure_open
from app.services.outbox import flush as flush_outbox

router = APIRouter(tags=["invites"])
GONE = "This invite link is no longer valid. Ask an organiser for a new one."


class CsvIn(BaseModel):
    csv: str = Field(max_length=300_000)


class AcceptIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


async def _rows(db: AsyncSession, season_id: int, body: CsvIn) -> list[svc.Row]:
    if not await db.get(Season, season_id):
        raise HTTPException(404, "Season not found")
    await ensure_open(db, season_id)
    try:
        rows = svc.parse(body.csv)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return await svc.check(db, season_id, rows)


@router.post("/admin/seasons/{season_id}/invites/preview")
async def preview(season_id: int, body: CsvIn, _: User = Depends(season_admin("season")), db: AsyncSession = Depends(get_session)) -> dict:
    rows = await _rows(db, season_id, body)
    return {"rows": [r.out() for r in rows], "ok": sum(1 for r in rows if not r.errors), "errors": sum(1 for r in rows if r.errors)}


@router.post("/admin/seasons/{season_id}/invites", status_code=201)
async def create(season_id: int, body: CsvIn, admin: User = Depends(season_admin("season")), db: AsyncSession = Depends(get_session)) -> dict:
    """Issue invites for every valid row. Rows with problems are returned and nothing is made for them."""
    await throttle("invite-create", str(admin.id), 20, 3600)
    rows = await _rows(db, season_id, body)
    made = await svc.create(db, season_id, rows, admin)
    if made:
        db.add(AuditLog(actor_id=admin.id, action="invite.create", entity="season", entity_id=season_id,
                        after={"count": len(made), "skipped": len(rows) - len(made)}))
    await db.commit()
    return {"invites": [{**_out(i), "token": t} for i, t in made], "skipped": [r.out() for r in rows if r.errors]}


def _out(i: Invite, teams: dict[int, str] | None = None) -> dict:
    return {"id": i.id, "name": i.name, "phone": i.phone, "team_id": i.team_id, "team": (teams or {}).get(i.team_id),
            "state": svc.state(i), "expires_at": i.expires_at.isoformat(), "created_at": i.created_at.isoformat()}


@router.get("/admin/seasons/{season_id}/invites")
async def listing(season_id: int, team_id: int | None = None, _: User = Depends(season_admin("season")),
                  db: AsyncSession = Depends(get_session)) -> list[dict]:
    q = select(Invite).where(Invite.season_id == season_id).order_by(Invite.id.desc()).limit(1000)
    if team_id:
        q = q.where(Invite.team_id == team_id)
    teams = {t.id: t.name for t in await db.scalars(select(Team).where(Team.season_id == season_id))}
    return [_out(i, teams) for i in await db.scalars(q)]  # never the secret: it is shown once, when issued


async def _open(db: AsyncSession, invite_id: int) -> Invite:
    inv = await db.scalar(select(Invite).where(Invite.id == invite_id).with_for_update())
    if not inv:
        raise HTTPException(404, "Invite not found")
    if inv.used_at:
        raise HTTPException(409, "This invite was already used")
    return inv


@router.post("/admin/invites/{invite_id}/revoke", status_code=204)
async def revoke(invite_id: int, admin: User = Depends(season_admin("invite")), db: AsyncSession = Depends(get_session)) -> None:
    inv = await _open(db, invite_id)
    inv.revoked_at = inv.revoked_at or datetime.now(UTC)
    db.add(AuditLog(actor_id=admin.id, action="invite.revoke", entity="invite", entity_id=inv.id))
    await db.commit()


@router.post("/admin/invites/{invite_id}/reissue", status_code=201)
async def reissue(invite_id: int, admin: User = Depends(season_admin("invite")), db: AsyncSession = Depends(get_session)) -> dict:
    """A lost or expired link: cancel the old one and make a new one for the same person."""
    old = await _open(db, invite_id)
    await ensure_open(db, old.season_id)
    if await db.scalar(select(User.id).where(User.phone == old.phone)):
        raise HTTPException(409, "This number now has an account")
    old.revoked_at = old.revoked_at or datetime.now(UTC)
    token = svc.new_token()
    new = Invite(token_hash=svc.hash_token(token), name=old.name, phone=old.phone, team_id=old.team_id, season_id=old.season_id,
                 created_by=admin.id, expires_at=datetime.now(UTC) + timedelta(days=svc.INVITE_DAYS))
    db.add(new)
    await db.flush()
    db.add(AuditLog(actor_id=admin.id, action="invite.reissue", entity="invite", entity_id=new.id, before={"old": old.id}))
    await db.commit()
    return {**_out(new), "token": token}


# ---------- the person with the link (no account yet) ----------
async def _by_token(db: AsyncSession, token: str, lock: bool = False) -> Invite:
    q = select(Invite).where(Invite.token_hash == svc.hash_token(token))
    inv = await db.scalar(q.with_for_update() if lock else q)
    if not inv or svc.state(inv) != "open":
        raise HTTPException(404, GONE)
    return inv


@router.get("/invites/{token}")
async def look(token: str, request: Request, db: AsyncSession = Depends(get_session)) -> dict:
    await throttle("invite-look", client_ip(request), 60, 3600)
    inv = await _by_token(db, token)
    team, season = await db.get(Team, inv.team_id), await db.get(Season, inv.season_id)
    return {"name": inv.name, "team": team.name if team else None, "season": season.name if season else None,
            "phone_ending": inv.phone[-2:]}


@router.post("/invites/{token}/accept", response_model=TokenOut, status_code=201)
async def accept(token: str, body: AcceptIn, request: Request, db: AsyncSession = Depends(get_session),
                 user_agent: str | None = Header(default=None)) -> TokenOut:
    await throttle("invite-accept", client_ip(request), 10, 3600)
    inv = await _by_token(db, token, lock=True)  # two people opening the same link cannot both get in
    await ensure_open(db, inv.season_id)
    team = await db.get(Team, inv.team_id)
    assert team is not None
    taken = await db.scalar(select(func.count()).select_from(TeamMember).where(TeamMember.team_id == team.id, TeamMember.status == "approved")) or 0
    if taken >= svc.MAX_ROSTER:
        raise HTTPException(409, f"{team.name} is full. Ask an organiser.")
    now = datetime.now(UTC)
    user = User(player_code="pending", name=inv.name, email=body.email.lower(), password_hash=await hash_password_async(body.password),
                phone=inv.phone, phone_verified=True, phone_verified_at=now, phone_verified_by=inv.created_by)
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(409, "That email or this number already has an account. Sign in, or ask an organiser.") from e
    user.player_code = f"FFP{user.id:05d}"
    db.add_all([UserRole(user_id=user.id, role="player"), TeamMember(team_id=team.id, user_id=user.id, status="approved")])
    inv.used_at, inv.used_by = now, user.id
    db.add(AuditLog(actor_id=user.id, action="invite.accept", entity="invite", entity_id=inv.id, after={"team": team.id}))
    await tell(db, {inv.created_by}, "roster", "Invite used", f"{inv.name} joined {team.name}.", "/admin/import", f"invite:{inv.id}:used")
    tokens = await _issue(db, user, user_agent)  # commits
    await flush_outbox(db)
    return tokens
