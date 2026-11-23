"""Helpers for the public (signed-out) side. Everything private is dropped here, in one place.

Public rules:
- A player appears by name unless they switched that off; then only their player code, and no id,
  so there is no page to link to. Suspended or banned players are never shown.
- Draft matches, seasons that are not public, chat, emails, phone numbers and unrevealed digits
  never reach a public response.
"""

import json
import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from fastapi import HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Match, Season, User
from app.realtime import client
from app.routers.auth import client_ip
from app.services.ratelimit import allow

log = logging.getLogger("ffcl.public")


def person_of(u: User) -> dict | None:
    """How a user may be shown to the public, or None if they must not be shown at all."""
    if u.status == "deleted":  # the person left: results keep a row for them, with no page and no code
        return {"id": None, "name": "Former player", "code": ""}
    if u.status != "active":
        return None
    if not u.show_publicly:
        return {"id": None, "name": u.player_code, "code": u.player_code}
    return {"id": u.id, "name": u.name, "code": u.player_code}


async def people(db: AsyncSession, ids: Iterable[int]) -> dict[int, dict | None]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    return {u.id: person_of(u) for u in await db.scalars(select(User).where(User.id.in_(wanted)))}


def name_of(known: dict[int, dict | None], uid: int | None) -> str | None:
    p = known.get(uid or 0)
    return p["name"] if p else None


async def public_season(db: AsyncSession, slug: str) -> Season:
    season = await db.scalar(select(Season).where(Season.slug == slug))
    if not season or not season.is_public or season.status == "draft":
        raise HTTPException(404, "Season not found")
    return season


async def public_match(db: AsyncSession, match_id: int) -> tuple[Match, Season]:
    m = await db.get(Match, match_id)
    season = await db.get(Season, m.season_id) if m else None
    if not m or m.published_at is None or not season or not season.is_public or season.status == "draft":
        raise HTTPException(404, "Match not found")
    return m, season


async def rate_limit(request: Request) -> None:
    """Dependency: a per-address ceiling for anonymous readers."""
    limit = settings.public_rate_limit_per_minute
    if limit and not await allow(f"rl:public:{client_ip(request)}", limit, 60):
        raise HTTPException(429, "Too many requests. Please slow down.")


def cache_headers(response: Response, seconds: int) -> None:
    response.headers["Cache-Control"] = f"public, max-age={seconds}, s-maxage={seconds}, stale-while-revalidate={seconds * 2}"


async def cached(key: str, ttl: int, build: Callable[[], Awaitable[Any]]) -> Any:
    """Shared short-lived cache for the heavy public reads. Fails open: no Redis means no cache."""
    if not settings.public_cache_enabled:
        return await build()
    k = f"pub:{key}"
    try:
        hit = await client().get(k)
        if hit is not None:
            return json.loads(hit)
    except Exception:
        log.warning("public cache unavailable", exc_info=True)
    value = await build()
    try:
        await client().set(k, json.dumps(value, default=str), ex=ttl)
    except Exception:
        log.warning("public cache write failed", exc_info=True)
    return value


def scrub_people(value: Any, known: dict[int, dict | None]) -> Any:
    """Walk a payload built by the signed-in code and replace every {id, name, player_code} person
    with how the public may see them. Players who may not be shown are removed from lists."""
    if isinstance(value, list):
        out = []
        for v in value:
            s = scrub_people(v, known)
            if s is not _DROP:
                out.append(s)
        return out
    if isinstance(value, dict):
        if "player_code" in value and "name" in value and "id" in value:
            p = known.get(value["id"])
            if p is None:
                return _DROP
            return {"id": p["id"], "name": p["name"], "player_code": p["code"]}
        res: dict[str, Any] = {}
        for k, v in value.items():
            s = scrub_people(v, known)
            if s is _DROP:
                if k in ("player", "top_batter", "top_bowler", "most_awards", "suggestion", "award"):
                    res[k] = None
                continue
            res[k] = s
        return res
    return value


_DROP: Any = object()
