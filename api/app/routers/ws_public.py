"""Anonymous live updates for a public match page. Read-only: the only thing sent is "changed, seq N",
after which the page refetches the public live view. No tokens, no digits, no private data."""

import asyncio
import contextlib
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.core.origin import refuse_foreign
from app.db.models import Match, Season
from app.realtime import channel, client, new_pubsub
from app.routers.ws import PING_SECONDS, log_task_failures, ws_db

router = APIRouter()


def _ip(ws: WebSocket) -> str:
    if settings.trust_proxy:
        fwd = ws.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return ws.client.host if ws.client else "unknown"


async def _take_slot(ip: str) -> bool:
    """Count this socket against the per-address and global caps (Redis, so it holds across workers)."""
    try:
        r = client()
        mine = await r.incr(f"ws:public:{ip}")
        await r.expire(f"ws:public:{ip}", 6 * 3600)  # safety net if a worker dies without releasing
        total = await r.incr("ws:public:total")
        if mine > settings.public_ws_per_ip or total > settings.public_ws_total:
            await _release(ip)
            return False
    except Exception:  # noqa: BLE001 - no Redis: do not lock anonymous readers out
        return True
    return True


async def _release(ip: str) -> None:
    with contextlib.suppress(Exception):
        r = client()
        if await r.decr(f"ws:public:{ip}") <= 0:
            await r.delete(f"ws:public:{ip}")
        if await r.decr("ws:public:total") < 0:
            await r.set("ws:public:total", 0)


@router.websocket("/ws/public/matches/{match_id}")
async def public_match_socket(ws: WebSocket, match_id: int) -> None:
    if await refuse_foreign(ws):
        return
    await ws.accept()
    async with ws_db(ws) as db:
        m = await db.get(Match, match_id)
        season = await db.get(Season, m.season_id) if m else None
        visible = bool(m and m.published_at is not None and season and season.is_public and season.status != "draft")
        seq = m.seq if m else 0
    if not visible:
        with contextlib.suppress(Exception):
            await ws.close(code=4404)
        return
    ip = _ip(ws)
    if not await _take_slot(ip):
        with contextlib.suppress(Exception):
            await ws.close(code=4429)
        return

    pubsub = new_pubsub()
    tasks: list[asyncio.Task] = []
    try:
        await pubsub.subscribe(channel(match_id))
        await ws.send_text(json.dumps({"type": "hello", "seq": seq}))

        async def pump() -> None:
            async for msg in pubsub.listen():
                if msg["type"] != "message":
                    continue
                data = msg["data"]
                try:
                    body = json.loads(data.decode() if isinstance(data, bytes) else data)
                except ValueError:
                    continue
                if body.get("type") == "changed":  # nothing else is ever forwarded
                    await ws.send_text(json.dumps({"type": "changed", "seq": body.get("seq")}))

        async def keepalive() -> None:
            while True:
                await asyncio.sleep(PING_SECONDS)
                await ws.send_text('{"type":"ping"}')

        async def drain() -> None:  # anything the client sends is ignored; this detects disconnects
            while True:
                await ws.receive_text()

        tasks = [asyncio.create_task(f()) for f in (pump, keepalive, drain)]
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        log_task_failures("public-match", tasks)
        for t in tasks:
            t.cancel()
        await _release(ip)
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(channel(match_id))
            await pubsub.aclose()
        with contextlib.suppress(Exception):
            await ws.close()
