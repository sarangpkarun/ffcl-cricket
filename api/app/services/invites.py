"""Bulk onboarding: parse a CSV of players, check every row, and issue one-time invite links.

A link is a random secret; only its hash is stored. Using it creates the account, marks the number as
verified by the admin who imported it, and puts the person in the team, all in one transaction.
"""

import csv
import io
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import sha256
from app.db.models import Invite, Team, TeamMember, User

MAX_ROWS = 500
MAX_BYTES = 200_000
INVITE_DAYS = 14
MAX_ROSTER = 7  # the same limit as adding a member by hand (routers/teams.py)
PHONE = re.compile(r"^\+?[0-9]{8,15}$")
# control characters, and the characters that reorder text so a name can pretend to be something else
BAD_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")


@dataclass
class Row:
    line: int
    name: str
    phone: str
    team: str
    team_id: int | None = None
    errors: list[str] = field(default_factory=list)

    def out(self) -> dict:
        return {"line": self.line, "name": self.name, "phone": self.phone, "team": self.team, "team_id": self.team_id,
                "ok": not self.errors, "errors": self.errors}


def hash_token(token: str) -> str:
    return sha256(token)


def new_token() -> str:
    return secrets.token_urlsafe(24)


def _cell(rec: list[str], i: int) -> str:
    return rec[i].strip() if i < len(rec) else ""


def parse(text: str) -> list[Row]:
    """Read the CSV (a header row with name, phone, team is required). Raises ValueError for a file that cannot be read."""
    if len(text.encode()) > MAX_BYTES:
        raise ValueError(f"The file is too large (limit {MAX_BYTES // 1000} KB)")
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    try:
        header = [h.strip().lower() for h in next(reader)]
    except StopIteration as e:
        raise ValueError("The file is empty") from e
    missing = [c for c in ("name", "phone", "team") if c not in header]
    if missing:
        raise ValueError("The first row must name the columns: name, phone, team (missing: " + ", ".join(missing) + ")")
    idx = {c: header.index(c) for c in ("name", "phone", "team")}
    rows: list[Row] = []
    for n, rec in enumerate(reader, start=2):
        if not any(c.strip() for c in rec):
            continue
        if len(rows) >= MAX_ROWS:
            raise ValueError(f"Too many rows (limit {MAX_ROWS}); split the file")
        rows.append(Row(n, _cell(rec, idx["name"]), re.sub(r"[\s-]", "", _cell(rec, idx["phone"])), _cell(rec, idx["team"])))
    if not rows:
        raise ValueError("The file has no players")
    return rows


async def check(db: AsyncSession, season_id: int, rows: list[Row]) -> list[Row]:
    """Fill in every problem with each row (does not write anything)."""
    teams = {t.name.strip().lower(): t for t in await db.scalars(select(Team).where(Team.season_id == season_id))}
    now = datetime.now(UTC)
    phones = [r.phone for r in rows if PHONE.match(r.phone)]
    registered = set(await db.scalars(select(User.phone).where(User.phone.in_(phones)))) if phones else set()
    invited = set(await db.scalars(select(Invite.phone).where(
        Invite.phone.in_(phones), Invite.used_at.is_(None), Invite.revoked_at.is_(None), Invite.expires_at > now))) if phones else set()
    seen: dict[str, int] = {}
    room: dict[int, int] = {}
    for t in teams.values():
        taken = await db.scalar(select(func.count()).select_from(TeamMember).where(TeamMember.team_id == t.id, TeamMember.status == "approved")) or 0
        open_invites = await db.scalar(select(func.count()).select_from(Invite).where(
            Invite.team_id == t.id, Invite.used_at.is_(None), Invite.revoked_at.is_(None), Invite.expires_at > now)) or 0
        room[t.id] = MAX_ROSTER - taken - open_invites
    for r in rows:
        if not r.name or len(r.name) > 120:
            r.errors.append("Name is missing or longer than 120 characters")
        elif BAD_CHARS.search(r.name):
            r.errors.append("Name contains control or direction-changing characters")
        if not PHONE.match(r.phone):
            r.errors.append("Phone must be 8 to 15 digits, with an optional leading +")
        else:
            if r.phone in registered:
                r.errors.append("This number already has an account")
            if r.phone in invited:
                r.errors.append("This number already has an open invite")
            if r.phone in seen:
                r.errors.append(f"Same number as line {seen[r.phone]}")
            seen.setdefault(r.phone, r.line)
        team = teams.get(r.team.strip().lower())
        if team is None:
            r.errors.append("No team with this name in the season")
        else:
            r.team_id = team.id
            if not r.errors:
                room[team.id] -= 1
                if room[team.id] < 0:
                    r.errors.append(f"{team.name} would have more than {MAX_ROSTER} players")
    return rows


async def create(db: AsyncSession, season_id: int, rows: list[Row], by: User) -> list[tuple[Invite, str]]:
    """Issue an invite for each row that has no errors. Returns (invite, secret); the secret is never stored."""
    out: list[tuple[Invite, str]] = []
    expires = datetime.now(UTC) + timedelta(days=INVITE_DAYS)
    for r in rows:
        if r.errors or r.team_id is None:
            continue
        token = new_token()
        inv = Invite(token_hash=hash_token(token), name=r.name, phone=r.phone, team_id=r.team_id, season_id=season_id,
                     created_by=by.id, expires_at=expires)
        db.add(inv)
        out.append((inv, token))
    await db.flush()
    return out


def state(inv: Invite, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    if inv.used_at:
        return "used"
    if inv.revoked_at:
        return "revoked"
    if inv.expires_at <= now:
        return "expired"
    return "open"
