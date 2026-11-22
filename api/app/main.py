import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine
from app.routers import auth, chat, live, matches, play, seasons, teams, users, ws, ws_rooms

app = FastAPI(title="FFCL API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
for r in (auth, users, seasons, teams, matches, play, live, ws, chat, ws_rooms):
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
