import asyncio
import contextlib
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.realtime import client, new_pubsub, user_channel
from app.routers.notifications import unread_count
from app.routers.ws import authenticate, log_task_failures, receive_token, session_alive, ws_db
from app.services.push import FG_SECONDS

router = APIRouter()
RECHECK_SECONDS = 25


@router.websocket("/ws/me")
async def me_socket(ws: WebSocket) -> None:
    """Pushes this user's new notifications. The first message must carry the access token."""
    await ws.accept()
    token = await receive_token(ws)
    async with ws_db(ws) as db:
        auth = await authenticate(db, token)
        unread = await unread_count(db, auth[0].id) if auth else 0
    if not auth:
        with contextlib.suppress(Exception):
            await ws.close(code=4401)
        return
    user, session_id = auth

    pubsub = new_pubsub()
    tasks: list[asyncio.Task] = []
    try:
        await pubsub.subscribe(user_channel(user.id))
        await ws.send_text(json.dumps({"type": "hello", "unread": unread}))

        async def pump() -> None:
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    data = msg["data"]
                    await ws.send_text(data.decode() if isinstance(data, bytes) else data)

        async def recheck() -> None:
            while True:
                await asyncio.sleep(RECHECK_SECONDS)
                async with ws_db(ws) as db:
                    alive = await session_alive(db, session_id, user.id)
                if not alive:
                    with contextlib.suppress(Exception):
                        await ws.close(code=4401)
                    return
                await ws.send_text('{"type":"ping"}')

        async def drain() -> None:
            """The page says "fg" while it is open and visible (about every 20 seconds) and "bg" when it is hidden.
            While a person is looking at the app they get notifications there, not as a push on top."""
            while True:
                try:
                    kind = json.loads(await ws.receive_text()).get("type")
                except (ValueError, AttributeError):
                    continue
                with contextlib.suppress(Exception):
                    if kind == "fg":
                        await client().set(f"fg:{user.id}", "1", ex=FG_SECONDS)
                    elif kind == "bg":
                        await client().delete(f"fg:{user.id}")

        tasks = [asyncio.create_task(f()) for f in (pump, recheck, drain)]
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        log_task_failures("notifications", tasks)
        with contextlib.suppress(Exception):
            await client().delete(f"fg:{user.id}")  # another open tab sends its next heartbeat within seconds
        for t in tasks:
            t.cancel()
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(user_channel(user.id))
            await pubsub.aclose()
        with contextlib.suppress(Exception):
            await ws.close()
