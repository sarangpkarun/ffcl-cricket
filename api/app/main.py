from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import assert_production_safe, settings
from app.db.session import engine
from app.routers import (
    adjustments,
    admin_audit,
    admin_rules,
    admin_users,
    auth,
    chat,
    declarations,
    duties,
    exports,
    fixtures,
    live,
    matches,
    moderation,
    notifications,
    phone_changes,
    play,
    public,
    push,
    roster,
    seasons,
    seasons_admin,
    standings,
    stats,
    teams,
    users,
    ws,
    ws_me,
    ws_public,
    ws_rooms,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    assert_production_safe(settings)
    yield


app = FastAPI(title="FFCL API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
for r in (auth, users, seasons, teams, matches, play, live, ws, chat, ws_rooms, moderation,
          notifications, ws_me, admin_users, fixtures, standings, declarations, duties, adjustments, stats, seasons_admin, roster, phone_changes, admin_rules, admin_audit, exports, public, ws_public, push):
    app.include_router(r.router)


@app.get("/health")
async def health() -> dict[str, str]:
    result = {"status": "ok", "db": "ok", "redis": "ok"}
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - health probe must never raise
        result["db"] = "down"
    try:
        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
    except Exception:  # noqa: BLE001 - health probe must never raise
        result["redis"] = "down"
    if "down" in (result["db"], result["redis"]):
        result["status"] = "degraded"
    return result
