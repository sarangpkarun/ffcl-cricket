import asyncio
import contextlib
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.realtime import new_pubsub, user_channel
from app.routers.notifications import unread_count
from app.routers.ws import authenticate, log_task_failures, receive_token, session_alive, ws_db

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
            while True:
                await ws.receive_text()

        tasks = [asyncio.create_task(f()) for f in (pump, recheck, drain)]
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        log_task_failures("notifications", tasks)
        for t in tasks:
            t.cancel()
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(user_channel(user.id))
            await pubsub.aclose()
        with contextlib.suppress(Exception):
            await ws.close()
